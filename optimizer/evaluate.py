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

from .search import group_stats, objective


def _boot_mean(x: np.ndarray, rng: np.random.Generator, B: int = 2000):
    if len(x) < 2:
        return [float(x.mean()) if len(x) else float("nan")] * 3
    b = rng.choice(x, (B, len(x))).mean(1)
    return [float(x.mean()), float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))]


def summarize(people, runs, trajs: Sequence[Sequence[float]], k: int, rng: np.random.Generator) -> Dict[str, Any]:
    st = group_stats(people, runs, trajs, k)
    raw = {g: np.array([t[k] - t[0] for (i, _, _, _), t in zip(runs, trajs) if people[i]["direction"] == g]) for g in (1, -1)}
    for g, name in ((1, "positive"), (-1, "negative")):
        st[name]["mean_signed_change_ci"] = _boot_mean(g * raw[g], rng)
        st[name]["mean_change_ci"] = _boot_mean(raw[g], rng)
    B = 2000
    if len(raw[1]) > 1 and len(raw[-1]) > 1:
        sep_b = rng.choice(raw[1], (B, len(raw[1]))).mean(1) - rng.choice(raw[-1], (B, len(raw[-1]))).mean(1)
        sep = [float(raw[1].mean() - raw[-1].mean()), float(np.quantile(sep_b, 0.025)), float(np.quantile(sep_b, 0.975))]
    else:
        sep = [float("nan")] * 3
    st["separation_change_ci"] = sep
    st["both_outward_ci_exclude_zero"] = bool(st["positive"]["mean_signed_change_ci"][1] > 0 and
                                              st["negative"]["mean_signed_change_ci"][1] > 0)
    return st


def per_participant(people, runs, trajs, k: int, rng) -> List[Dict[str, Any]]:
    rows = []
    for i, p in enumerate(people):
        x = np.array([t[k] - t[0] for (j, _, _, _), t in zip(runs, trajs) if j == i])
        if not len(x):
            continue
        d = p["direction"] or 1
        ci = _boot_mean(d * x, rng)
        rows.append({"participant": p["id"], "group": {1: "positive", -1: "negative", 0: "neutral"}[p["direction"]],
                     "I0": round(p["I0"], 5), "runs": len(x), "mean_change": round(float(x.mean()), 5),
                     "mean_signed_change": round(ci[0], 5), "ci_low": round(ci[1], 5), "ci_high": round(ci[2], 5),
                     "share_outward": round(float((d * x > 0).mean()), 3) if p["direction"] else None})
    return rows


def baselines(sim, people, bank, length: int, n: int, reps: int, seed0: int, mode: str, kind: str, seq_ids: List[str]):
    """Random sequences vs the optimized one, all on the same baseline runs."""
    runs = sim.make_runs(people, reps, seed0)
    by_id = {q["id"]: q for q in bank}
    rng = random.Random(seed0)
    rows = []
    for b in range(n):
        ids = rng.sample(list(by_id), min(length, len(by_id)))
        st = group_stats(people, runs, sim.simulate(runs, [by_id[i]["variables"] for i in ids], mode))
        rows.append({"baseline": b + 1, "objective": objective(st, kind), "t_positive": st["positive"]["t"],
                     "t_negative": st["negative"]["t"], "mean_positive": st["positive"]["mean_signed_change"],
                     "mean_negative": st["negative"]["mean_signed_change"],
                     "separation_change": st["positive"]["mean_signed_change"] + st["negative"]["mean_signed_change"],
                     "sequence": ";".join(ids)})
    st = group_stats(people, runs, sim.simulate(runs, [by_id[i]["variables"] for i in seq_ids], mode))
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
    lines += ["", "## Reading this", "",
              "- Effects are population averages under sampled answers; individual runs vary a lot (see `share_outward`).",
              "- Each question is answered through the survey items it maps to (`question_set_detail.csv`). In the web app,",
              "  check each answer's *Model evidence* to confirm the same items are selected.",
              "- Results depend on the model wave, the poles and the participants; re-run for other settings.", ""]
    return "\n".join(lines)
