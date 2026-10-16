"""Held-out validation, random baselines and the report files.

Validation runs use seeds that the search never saw: new perturbed starting states and new
answer draws. Per group (positive / negative starting ideology) we report the mean *signed*
change (direction x change; > 0 means moved outward) with a 95% bootstrap CI, its t value and the
share of runs that moved outward, for every prefix length. The separation change is the
difference between the two groups' mean raw changes (positive minus negative), with a CI from
resampling the two groups independently. Random sequences of the same length from the same bank,
scored on their own runs, give the baseline.
"""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np

from .search import group_stats, objective, run_direction


def _boot_mean(x: np.ndarray, rng: np.random.Generator, B: int = 2000):
    if len(x) < 2:
        return [float(x.mean()) if len(x) else float("nan")] * 3
    b = rng.choice(x, (B, len(x))).mean(1)
    return [float(x.mean()), float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))]


def summarize(people, runs, trajs, k, rng, neutral_band=0.005):
    st = group_stats(people, runs, trajs, k=k, neutral_band=neutral_band)
    raw = {g: np.array([t[k] - t[0] for r, t in zip(runs, trajs)
                        if run_direction(r, neutral_band) == g]) for g in (1, -1)}
    for g, name in ((1, "positive"), (-1, "negative")):
        st[name]["mean_signed_change_ci"] = _boot_mean(g * raw[g], rng)
        st[name]["mean_change_ci"] = _boot_mean(raw[g], rng)
    B = 2000
    if len(raw[1]) > 1 and len(raw[-1]) > 1:
        sep_b = rng.choice(raw[1], (B, len(raw[1]))).mean(1) - rng.choice(raw[-1], (B, len(raw[-1]))).mean(1)
        sep = [float(raw[1].mean() - raw[-1].mean()), float(np.quantile(sep_b, .025)),
               float(np.quantile(sep_b, .975))]
    else:
        sep = [float("nan")] * 3
    st["separation_change_ci"] = sep
    st["both_outward_ci_exclude_zero"] = bool(
        st["positive"]["mean_signed_change_ci"][1] > 0 and
        st["negative"]["mean_signed_change_ci"][1] > 0)
    return st


def per_participant(people, runs, trajs, k, rng, neutral_band=0.005):
    rows = []
    for i, p in enumerate(people):
        samples = [(r, t) for r, t in zip(runs, trajs) if r[0] == i]
        if not samples:
            continue
        raw = np.asarray([t[k] - t[0] for r, t in samples])
        direction = np.asarray([run_direction(r, neutral_band) for r, t in samples])
        signed = direction * raw
        directed = signed[direction != 0]
        ci = _boot_mean(directed, rng)
        rows.append({"participant": p["id"], "group": {1:"positive",-1:"negative",0:"neutral"}[p["direction"]],
                     "I0": round(p["I0"], 5), "runs": len(raw), "mean_change": round(float(raw.mean()),5),
                     "mean_signed_change": ci[0], "ci_low": ci[1], "ci_high": ci[2],
                     "share_outward": float((directed>0).mean()) if len(directed) else None})
    return rows


def state_diagnostics(people, runs, trajectories, length, rng, neutral_band=0.005):
    """Cluster trajectories by starting state; bootstrap STATES, not answer draws."""
    grouped, state_meta = {}, {}
    for r, t in zip(runs, trajectories):
        sid = r[4] if len(r) > 4 else f"{r[0]}:{r[3]}"
        grouped.setdefault(sid, []).append(float(t[length] - t[0]))
        state_meta[sid] = r
    rows = []
    for sid, values in grouped.items():
        run = state_meta[sid]
        p = people[run[0]]
        direction = run_direction(run, neutral_band)
        raw = np.asarray(values, dtype=float)
        signed = direction * raw
        ci = _boot_mean(signed, rng) if direction else [float("nan")] * 3
        rows.append({"state_id": sid, "participant": p["id"], "original_group": p["direction"],
                     "start_group": direction, "sign_flipped_or_neutral": direction != p["direction"],
                     "I_start": float(run[2]), "draws": len(raw), "mean_change": float(raw.mean()),
                     "mean_signed_change": float(signed.mean()) if direction else float("nan"),
                     "ci_low": ci[1], "ci_high": ci[2],
                     "share_outward": float((signed > 0).mean()) if direction else float("nan")})
    groups = {}
    for g, name in ((1,"positive"),(-1,"negative")):
        chosen = [row for row in rows if row["start_group"] == g]
        values = np.asarray([row["mean_signed_change"] for row in chosen], dtype=float)
        groups[name] = {"n_states": len(values), "mean_signed_change_ci": _boot_mean(values, rng),
                        "share_states_mean_outward": float((values > 0).mean()) if len(values) else float("nan")}
    flips = sum(row["sign_flipped_or_neutral"] for row in rows)
    return rows, {"n_states": len(rows), "n_sign_flips_or_neutral": flips,
                  "groups": groups,
                  "note": "Uncertainty across perturbed states conditional on the selected persona templates and fixed LSM."}


def order_controls(sim, people, runs, bank, seq_ids, n, mode, neutral_band, seed):
    if n <= 0 or len(seq_ids) < 2:
        return []
    by_id = {q["id"]: q for q in bank}
    randomizer = random.Random(seed)
    rows = []
    for j in range(n):
        order = list(seq_ids)
        randomizer.shuffle(order)
        if order == seq_ids:
            order = order[1:] + order[:1]
        st = group_stats(people, runs,
                         sim.simulate(runs, [by_id[q]["variables"] for q in order], mode),
                         neutral_band=neutral_band)
        rows.append({"baseline": j+1, "t_positive": st["positive"]["t"],
                     "t_negative": st["negative"]["t"],
                     "mean_positive": st["positive"]["mean_signed_change"],
                     "mean_negative": st["negative"]["mean_signed_change"],
                     "separation_change": st["positive"]["mean_signed_change"]+
                                          st["negative"]["mean_signed_change"],
                     "sequence": ";".join(order)})
    return rows


def baselines(sim, people, bank, length: int, n: int, reps: int, seed0: int, mode: str, kind: str, seq_ids: List[str], neutral_band: float = 0.005,
              validation_runs=None):
    """Compare random sequences on MATCHED initial states, limiting draws per state."""
    if validation_runs is not None:
        counts = {}
        runs = []
        for r in validation_runs:
            sid = r[4] if len(r) > 4 else (r[0], r[3])
            if counts.get(sid, 0) < reps:
                runs.append(r)
                counts[sid] = counts.get(sid, 0) + 1
    else:
        runs = sim.make_runs(people, reps, seed0)
    by_id = {q["id"]: q for q in bank}
    rng = random.Random(seed0)
    rows = []
    for b in range(n):
        ids = rng.sample(list(by_id), min(length, len(by_id)))
        st = group_stats(people, runs, sim.simulate(runs, [by_id[i]["variables"] for i in ids], mode), neutral_band=neutral_band)
        rows.append({"baseline": b + 1, "objective": objective(st, kind), "t_positive": st["positive"]["t"],
                     "t_negative": st["negative"]["t"], "mean_positive": st["positive"]["mean_signed_change"],
                     "mean_negative": st["negative"]["mean_signed_change"],
                     "separation_change": st["positive"]["mean_signed_change"] + st["negative"]["mean_signed_change"],
                     "sequence": ";".join(ids)})
    st = group_stats(people, runs, sim.simulate(runs, [by_id[i]["variables"] for i in seq_ids], mode), neutral_band=neutral_band)
    opt = {"objective": objective(st, kind),
           "separation_change": st["positive"]["mean_signed_change"] + st["negative"]["mean_signed_change"]}
    pct = lambda key: float(np.mean([r[key] < opt[key] for r in rows])) if rows else float("nan")  # noqa: E731
    return rows, {"optimized_on_baseline_runs": opt, "percentile_objective": pct("objective"),
                  "percentile_separation_change": pct("separation_change"), "n": n, "runs_per_participant": reps}


# ---------------------------------------------------------------------------------- files

def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_question_set(path: Path, questions: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["step", "question"])
        for i, q in enumerate(questions, 1):
            w.writerow([i, q])


def fmt_ci(ci) -> str:
    return "—" if not ci or any(isinstance(v, float) and math.isnan(v) for v in ci) else f"{ci[0]:+.4f} [{ci[1]:+.4f}, {ci[2]:+.4f}]"


def report_md(cfg: Dict[str, Any], manifest: Dict[str, Any], people, seq_detail, val, per_len, base_summary,
              part_rows) -> str:
    L = val["length"]
    s = val["summary"]
    lines = [
        "# Polarization question set — optimizer report", "",
        "Simulation and model-sensitivity output for synthetic DTAG respondents. Not intended for targeting,",
        "persuasion, campaigning or influencing real people.", "",
        f"- Model `{manifest['model']['key']}` · map `{manifest['map']['file']}` (sha256 {manifest['map']['sha256'][:12]}…)"
        f" · poles `{manifest['poles']['file']}` ({manifest['poles']['items']} items)",
        f"- Answers: `{cfg['search']['resp_mode']}` with state updates · LLM: {json.dumps(manifest['llm'])}",
        f"- Participants: {sum(p['direction'] == 1 for p in people)} positive, {sum(p['direction'] == -1 for p in people)} negative,"
        f" {sum(p['direction'] == 0 for p in people)} neutral (|I0| < {cfg['participants']['neutral_band']})",
        f"- Bank: {manifest['bank_size']} questions ({cfg['bank']['source']}, mapping `{cfg['bank']['mapping']}`)", "",
        f"## Recommended set ({L} questions) — `question_set.csv`", "",
        "| Step | Question | Survey items |", "|---:|---|---|"]
    lines += [f"| {r['step']} | {r['question'].replace('|', '/')} | `{r['variables']}` |" for r in seq_detail[:L]]
    lines += ["", f"## Held-out validation ({val['runs_per_participant']} runs per participant, seeds unseen by the search)", "",
              "| Group | Mean signed change [95% CI] | t | Runs moving outward |", "|---|---|---:|---:|"]
    for g in ("positive", "negative"):
        lines.append(f"| {g} (should move {'up' if g == 'positive' else 'down'}) | {fmt_ci(s[g]['mean_signed_change_ci'])} |"
                     f" {s[g]['t']:+.2f} | {s[g]['share_outward']:.0%} |")
    lines += ["", f"Separation change (positive mean change − negative mean change): **{fmt_ci(s['separation_change_ci'])}**."
              f" Both groups' CIs exclude zero: **{'yes' if s['both_outward_ci_exclude_zero'] else 'no'}**.", ""]
    if base_summary:
        lines += [f"Against {base_summary['n']} random {L}-question sequences from the same bank (own runs): the optimized set's"
                  f" objective beats {base_summary['percentile_objective']:.0%} of them and its separation change"
                  f" {base_summary['percentile_separation_change']:.0%}.", ""]
    lines += ["## Every length", "", "| Length | Positive: signed change [CI] | Negative: signed change [CI] | Separation [CI] |",
              "|---:|---|---|---|"]
    lines += [f"| {r['length']} | {fmt_ci(r['positive']['mean_signed_change_ci'])} | {fmt_ci(r['negative']['mean_signed_change_ci'])}"
              f" | {fmt_ci(r['separation_change_ci'])} |" for r in per_len]
    lines += ["", "## Participants", "", "| Participant | Group | I0 | Mean signed change [CI] | Outward |", "|---|---|---:|---|---:|"]
    lines += [f"| {r['participant']} | {r['group']} | {r['I0']:+.4f} | {r['mean_signed_change']:+.4f} [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}] |"
              f" {'' if r['share_outward'] is None else format(r['share_outward'], '.0%')} |" for r in part_rows]
    sd = val.get("state_diagnostics")
    if sd:
        lines += ["", "## Across distinct starting states", "",
                  f"States={sd['n_states']}; changes of original sign or entry into neutral band="
                  f"{sd['n_sign_flips_or_neutral']}.",
                  "Intervals here bootstrap distinct starting states, not response draws.",
                  "They describe variation around these persona templates, not survey-population generalization.", "",
                  "| Actual starting side | States | State-mean signed change [95% CI] | States moving outward on average |",
                  "|---|---:|---|---:|"]
        for name in ("positive", "negative"):
            g = sd["groups"][name]
            lines.append(f"| {name} | {g['n_states']} | {fmt_ci(g['mean_signed_change_ci'])} | "
                         f"{g['share_states_mean_outward']:.0%} |")
        lines += ["", "See per_state.csv, starting_states.jsonl and state_diagnostics.json.", ""]
    lines += ["", "## Reading this", "",
              "- Effects are fixed-model, persona-conditional averages under sampled answers; individual runs vary a lot (see `share_outward`).",
              "- Each question is answered through the survey items it maps to (`question_set_detail.csv`). In the web app,",
              "  check each answer's *Model evidence* to confirm the same items are selected.",
              "- Results depend on the model wave, the poles and the participants; re-run for other settings.", ""]
    return "\n".join(lines)
