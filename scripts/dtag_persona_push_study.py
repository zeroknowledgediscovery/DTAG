#!/usr/bin/env python3
"""Reproducible GSS persona-push study for DTAG figure generation.

Six pinned personas (3 left, 3 right), four native question policies:
right / left / neutral_mu (min |expected delta|) / random.
Each policy reselects the next eligible opinion *item* at the current sampled
LSM state. Responses are drawn, never prescribed. No LLM, no political
messaging to humans, and no claim that simulated conditioning is persuasion.

The engine is optimizer.one_step_geometry.policy_run. Results include raw
run/step CSV, bootstrap 95% CI by step, matched-run end contrasts versus
random, machine provenance, and a two-column/three-row journal figure.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

POLICIES = ("right", "left", "neutral", "random")
SELECTED = {
    "right": ("cm_rural_alabama", "religious_conservative_woman_texas",
              "hispanic_catholic_man_arizona"),
    "left": ("wf_new_york_city", "secular_liberal_man_seattle",
             "black_churchgoing_woman_atlanta"),
}
PAIRS = (
    ("cm_rural_alabama", "wf_new_york_city"),
    ("religious_conservative_woman_texas", "secular_liberal_man_seattle"),
    ("hispanic_catholic_man_arizona", "black_churchgoing_woman_atlanta"),
)


def stable_seed(seed: int, persona: str, repetition: int, policy: str) -> int:
    """Stable across Python processes and PYTHONHASHSEED settings."""
    blob = f"{seed}|{persona}|{repetition}|{policy}".encode()
    return int.from_bytes(hashlib.sha256(blob).digest()[:8], "big")


def bootstrap_means(x, nboot: int = 2000, seed: int = 0):
    """CI on the conditional Monte Carlo mean; one independent run is the unit."""
    z = np.asarray(x, dtype=float)
    if len(z) == 0:
        return (float("nan"), float("nan"), float("nan"))
    mean = float(z.mean())
    if len(z) == 1:
        return mean, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    # Chunked to avoid materializing a very large bootstrap index matrix.
    draws = np.empty(nboot)
    for a in range(0, nboot, 250):
        b = min(a + 250, nboot)
        draws[a:b] = z[rng.integers(len(z), size=(b - a, len(z)))].mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return mean, float(lo), float(hi)


def load_personas(path: Path):
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    available = {p["id"]: p for p in data["participants"]}
    chosen = [i for pair in PAIRS for i in pair]
    missing = set(chosen) - set(available)
    if missing:
        raise ValueError(f"Persona IDs missing from {path}: {sorted(missing)}")
    for pid in chosen:
        p = available[pid]
        if not isinstance(p.get("state"), dict) or not p["state"]:
            raise ValueError(f"{pid}: requires a pinned state (no LLM decoding)")
        if p["state"].get("polviews") in (None, ""):
            raise ValueError(f"{pid}: missing polviews anchor")
    return [(pid, "right" if pid in SELECTED["right"] else "left",
             dict(available[pid]["state"]), available[pid].get("text", ""))
            for pid in chosen]


def eligible_opinion_items(world):
    """Exactly the same item eligibility predicate as webapp push suggestions."""
    from optimize_question_sets import askable
    poles = set(world.g.left_map) | set(world.g.right_map)
    feat = set(world.ctx.feat)
    return sorted(v for v in world.ctx.idx_map
                  if v not in poles and v in world.ctx.var_map
                  and world.ctx.possible.get(v)
                  and askable(v, world.ctx.var_map.get(v, ""), feat))


# One cached native World per executor process.
_WORLD = None
_ONLY = None


def worker_init(model_path, map_path, poles_path, native_cache):
    global _WORLD, _ONLY
    from optimizer.dtag_bridge import World
    _WORLD = World(model_path, map_path, poles_path, native_cache)
    if not getattr(_WORLD.m, "has_extension_distances", False):
        raise RuntimeError("Native LSM incremental evaluator missing; run bash scripts/build_native_bindings.sh")
    _ONLY = eligible_opinion_items(_WORLD)
    if len(_ONLY) < 20:
        raise RuntimeError(f"Too few eligible opinion questions: {len(_ONLY)}")


def run_one(job):
    from optimizer.one_step_geometry import policy_run, strict_native_index

    persona, side, pinned, rep, policy, steps, master_seed = job
    state, dropped = _WORLD.valid(pinned)
    if dropped:
        raise ValueError(f"{persona}: invalid pinned assignments: {dropped}")
    i0 = strict_native_index(_WORLD, state)
    actual_policy = {"right": "greedy_mu", "left": "greedy_mu",
                     "neutral": "neutral_mu", "random": "random"}[policy]
    # We deliberately keep *all* pinned coordinates immutable. The policy
    # cannot select those coordinates because they are in the current state.
    direction = "left" if policy == "left" else "right"
    rng = np.random.default_rng(stable_seed(master_seed, persona, rep, policy))
    seq = policy_run(_WORLD, state, direction=direction, steps=steps,
                     rng=rng, policy=actual_policy, exclude_poles=True,
                     only=_ONLY)
    records = [{
        "persona": persona, "lean": side, "rep": rep, "policy": policy,
        "step": 0, "I": float(i0), "delta_I": 0., "net_delta": 0.,
        "variable": "", "question": "", "answer": "", "p_answer": "",
        "expected_delta": "", "one_sided": ""
    }]
    for step in seq:
        records.append({
            "persona": persona, "lean": side, "rep": rep, "policy": policy,
            "step": int(step["step"]), "I": float(step["I_after"]),
            "delta_I": float(step["delta_I"]), "net_delta": float(step["I_after"] - i0),
            "variable": step["variable"], "question": step["question_text"],
            "answer": step["answer"], "p_answer": step["p_answer"],
            "expected_delta": step.get("expected_delta"),
            "one_sided": step.get("one_sided"),
        })
    # Carry forward a stopped run with clear (not silently missing) endpoint.
    if len(records) < steps + 1:
        for t in range(len(records), steps + 1):
            old = dict(records[-1])
            old.update(step=t, delta_I=0., variable="", question="",
                       answer="", p_answer="", expected_delta="", one_sided="")
            records.append(old)
    return records


FIELDS = ("persona", "lean", "rep", "policy", "step", "I", "delta_I",
          "net_delta", "variable", "question", "answer", "p_answer",
          "expected_delta", "one_sided")


def csv_write(path: Path, rows, names):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=names, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def summarize(rows, persons, steps, reps, nboot, seed):
    lookup = {(r["persona"], r["policy"], r["rep"], r["step"]): float(r["net_delta"])
              for r in rows}
    level = {(r["persona"], r["policy"], r["rep"], r["step"]): float(r["I"])
             for r in rows}
    ci = []
    ends = []
    contrasts = []
    for pi, (persona, side, _, _) in enumerate(persons):
        all_start = [level[persona, "random", rep, 0] for rep in range(reps)]
        if len(set(round(x, 12) for x in all_start)) != 1:
            raise AssertionError("Pinned persona baseline varied across seeds")
        i0 = float(all_start[0])
        for ai, arm in enumerate(POLICIES):
            for t in range(steps + 1):
                z = [lookup[persona, arm, rep, t] for rep in range(reps)]
                mean, lo, hi = bootstrap_means(z, nboot, seed + 10000*pi + 100*ai + t)
                ci.append({"persona": persona, "lean": side, "policy": arm,
                           "step": t, "initial_I": i0,
                           "mean_net_delta": mean, "ci_low": lo, "ci_high": hi,
                           "mean_I": mean + i0, "ci_I_low": lo + i0, "ci_I_high": hi + i0,
                           "n": reps})
            vals = np.array([lookup[persona, arm, rep, steps] for rep in range(reps)])
            m, lo, hi = bootstrap_means(vals, nboot, seed + 10000*pi + 100*ai + 999)
            ends.append({"persona": persona, "lean": side, "policy": arm,
                         "initial_I": i0, "mean_delta": m, "ci_low": lo,
                         "ci_high": hi, "n": reps,
                         "positive_share": float(np.mean(vals > 0)),
                         "negative_share": float(np.mean(vals < 0)),
                         "sd": float(vals.std(ddof=1)) if reps > 1 else float("nan")})
            if arm != "random":
                diffs = np.array([lookup[persona, arm, rep, steps]
                                  - lookup[persona, "random", rep, steps]
                                  for rep in range(reps)])
                dmean, dlo, dhi = bootstrap_means(diffs, nboot,
                                                  seed + 10000*pi + 100*ai + 333)
                contrasts.append({"persona": persona, "lean": side, "policy": arm,
                                  "versus": "random", "n": reps, "mean_difference": dmean,
                                  "ci_low": dlo, "ci_high": dhi})
    return ci, ends, contrasts


def render_figure(ci, ends, contrasts, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grouped = {(r["persona"], r["policy"]): [] for r in ci}
    for r in ci:
        grouped[r["persona"], r["policy"]].append(r)
    fig, axes = plt.subplots(3, 2, figsize=(10.4, 10.5), sharex=True)
    labels = {"right": "Push right", "left": "Push left",
              "neutral": "Neutral (min |expected shift|)",
              "random": "Random opinion item"}
    for ri, pair in enumerate(PAIRS):
        for cj, persona in enumerate(pair):
            ax = axes[ri, cj]
            for arm in POLICIES:
                sub = sorted(grouped[persona, arm], key=lambda r: r["step"])
                x = np.array([v["step"] for v in sub])
                m = np.array([v["mean_net_delta"] for v in sub])
                low = np.array([v["ci_low"] for v in sub])
                high = np.array([v["ci_high"] for v in sub])
                line, = ax.plot(x, m, lw=1.65, label=labels[arm])
                if np.isfinite(low).all() and np.isfinite(high).all():
                    ax.fill_between(x, low, high, color=line.get_color(), alpha=.14, lw=0)
            ax.axhline(0, color="0.45", lw=.8, ls=":")
            initial = next(r["initial_I"] for r in ends if r["persona"] == persona)
            lean = "Conservative" if cj == 0 else "Liberal"
            ax.set_title(f"{lean} persona {ri+1}: {persona.replace('_',' ')}\n"
                         f"Initial geometric index = {initial:+.3f}", fontsize=9)
            ax.set_ylabel(r"$I_t-I_0$")
            if ri == 2:
                ax.set_xlabel("Questions asked")
            ax.grid(alpha=.20)
    handles, leglabels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, leglabels, loc="upper center", ncol=4, frameon=False,
               bbox_to_anchor=(.5, .998), fontsize=9)
    fig.suptitle("DTAG adaptive-question trajectories (native GSS model; 95% Monte Carlo CI)",
                 fontsize=12, y=1.037)
    fig.tight_layout(rect=(0, 0, 1, .96), h_pad=1.2)
    fig.savefig(out / "persona_push_trajectories.pdf", bbox_inches="tight")
    fig.savefig(out / "persona_push_trajectories.png", dpi=190, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for k, side in enumerate(("right", "left")):
        ax = axes[k]
        members = SELECTED[side]
        offsets = np.arange(len(members))
        for j, arm in enumerate(POLICIES):
            records = [next(e for e in ends if e["persona"] == name and e["policy"] == arm)
                       for name in members]
            shifts = np.array([e["mean_delta"] for e in records])
            left = np.array([e["ci_low"] for e in records])
            right = np.array([e["ci_high"] for e in records])
            color = f"C{j}"
            ax.errorbar(shifts, offsets + (j - 1.5) * .16,
                        xerr=np.array([shifts-left, right-shifts]),
                        fmt="o", ms=4, lw=1.2, capsize=2, color=color,
                        label=labels[arm] if k == 0 else None)
        ax.set_yticks(offsets, [v.replace("_", " ") for v in members], fontsize=8)
        ax.axvline(0, ls=":", lw=.8, color="0.5")
        ax.set_xlabel(r"Net geometric displacement $I_T-I_0$")
        ax.set_title("Conservative anchor" if side == "right" else "Liberal anchor")
        ax.grid(axis="x", alpha=.2)
    fig.legend(loc="upper center", ncol=4, bbox_to_anchor=(.5, 1.02),
               frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, .90))
    fig.savefig(out / "persona_push_endpoints.pdf", bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="gss/gss_2024")
    ap.add_argument("--personas", type=Path,
                    default=ROOT / "optimizer/personas/gss2024_spectrum.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs/dtag_persona_push")
    ap.add_argument("--reps", type=int, default=40,
                    help="independent stochastic draws per persona/policy")
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--quick", action="store_true",
                    help="plumbing / speed check: 2 repetitions x 3 steps (no publishable CI)")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--skip-figures", action="store_true")
    a = ap.parse_args(argv)
    if a.quick:
        a.reps, a.steps = 2, 3
    if a.reps < 2 or a.steps < 1 or a.workers < 1 or a.bootstrap < 100:
        ap.error("--reps>=2, --steps>=1, --workers>=1, --bootstrap>=100 required")
    a.out.mkdir(parents=True, exist_ok=True)

    from optimizer.dtag_bridge import DEFAULT_POLES, canonical_map, ensure_model, sha256, World

    model_dir = ensure_model(a.model, None, download=not a.no_download)
    map_path = canonical_map(a.model)
    pole_path = DEFAULT_POLES
    cache_path = a.out / "native_cache"
    cache_path.mkdir(parents=True, exist_ok=True)
    persons = load_personas(a.personas)
    world = World(str(model_dir), str(map_path), str(pole_path), str(cache_path))
    only = eligible_opinion_items(world)
    if len(only) < a.steps or not world.g.enabled:
        raise RuntimeError("Missing model poles or insufficient eligible questions")
    for persona, side, state, _ in persons:
        good, dropped = world.valid(state)
        if dropped:
            raise ValueError(f"{persona}: pinned assignments are invalid: {dropped}")
        print(f"{persona:43} {side:5} I0={world.I(good):+.5f}", flush=True)
    del world

    jobs = [(pid, side, s, rep, policy, a.steps, a.seed)
            for pid, side, s, _ in persons for rep in range(a.reps)
            for policy in POLICIES]
    # Random policy executions are independent per iteration; summarize in
    # stable order to ensure independent of worker scheduling.
    rows = []
    args = (str(model_dir), str(map_path), str(pole_path), str(cache_path))
    if a.workers == 1:
        worker_init(*args)
        for k, job in enumerate(jobs, 1):
            rows.extend(run_one(job))
            if k % 12 == 0:
                print(f"{k}/{len(jobs)} runs completed", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=a.workers, initializer=worker_init,
                                 initargs=args) as pool:
            futures = {pool.submit(run_one, job): job for job in jobs}
            for k, f in enumerate(as_completed(futures), 1):
                rows.extend(f.result())
                if k % 12 == 0:
                    print(f"{k}/{len(jobs)} runs completed", flush=True)
    order = {p[0]: n for n, p in enumerate(persons)}
    arm_order = {p: n for n, p in enumerate(POLICIES)}
    rows.sort(key=lambda r: (order[r["persona"]], arm_order[r["policy"]],
                             r["rep"], r["step"]))
    csv_write(a.out / "trajectories.csv", rows, FIELDS)
    ci, ends, contrasts = summarize(rows, persons, a.steps, a.reps, a.bootstrap, a.seed)
    csv_write(a.out / "trajectory_ci.csv", ci,
              ("persona", "lean", "policy", "step", "initial_I", "mean_net_delta",
               "ci_low", "ci_high", "mean_I", "ci_I_low", "ci_I_high", "n"))
    csv_write(a.out / "endpoints.csv", ends,
              ("persona", "lean", "policy", "initial_I", "mean_delta",
               "ci_low", "ci_high", "n", "positive_share", "negative_share", "sd"))
    csv_write(a.out / "versus_random.csv", contrasts,
              ("persona", "lean", "policy", "versus", "n", "mean_difference",
               "ci_low", "ci_high"))
    counts = Counter((r["persona"], r["policy"], r["variable"]) for r in rows
                     if r["variable"])
    csv_write(a.out / "question_counts.csv",
              (dict(persona=p, policy=arm, variable=v, n=n)
               for (p, arm, v), n in sorted(counts.items())),
              ("persona", "policy", "variable", "n"))
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                         stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = "unavailable"
    manifest = {
        "experiment": "dtAG_GSS_persona_pole_push_vs_neutral_random",
        "study_design": "six fixed pinned synthetic GSS personas; up/down/neutral/random",
        "interpretation": "95% bootstrap CI of synthetic response-draw means conditional on each "
                          "fixed persona and fitted LSM; not human effect estimates",
        "model": a.model, "model_path": str(model_dir),
        "map_sha256": sha256(map_path), "poles_sha256": sha256(Path(pole_path)),
        "git_commit": commit, "persona_file": str(a.personas),
        "persona_sha256": sha256(a.personas),
        "initial_states": {pid: state for pid, _, state, _ in persons},
        "seed": a.seed, "repetitions": a.reps, "steps": a.steps,
        "bootstrap_samples": a.bootstrap, "eligible_items": len(only),
        "exclude_pole_items": True, "response_mode": "draw",
        "question_mode": "direct native survey item, no LLM mapping",
        "policies": POLICIES, "workers": a.workers, "quick": a.quick,
    }
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not a.skip_figures:
        render_figure(ci, ends, contrasts, a.out)
    print(f"Completed {len(jobs)} native synthetic trajectories: {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
