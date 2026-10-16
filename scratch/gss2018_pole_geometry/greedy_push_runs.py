#!/usr/bin/env python3
"""Push a persona left or right by asking survey items one at a time (native GSS 2018 LSM).

One case = one persona (CM | WF) and one direction (right | left). Each run asks --n-items
items. At every step:

  greedy_mu  re-scores every candidate item exactly at the current state
             (optimizer.one_step_geometry) and asks the item with the largest expected move
             mu in the requested direction (argmax mu for right, argmin mu for left);
  random     asks a uniformly random candidate item (baseline).

The response is drawn from the native P(response | state, item). The asker never chooses it.
The state is updated and the centered index J = I - I(empty) is recomputed.
Pole-defining items are never asked.

Printed for every step: item, response, and J after the step. A per-run table is printed at
the end of each run. Saved to --out:

  <PERSONA>_<direction>_n<N>.csv        every step of every run (item, response, probability,
                                         mu, realized dJ, J after, expected J = J0 + cumulative mu)
  <PERSONA>_<direction>_n<N>.json       state, seed, J0, settings (+ audit)

Usage (from anywhere; the first run builds the native binding and downloads gss/gss_2018):

    python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona CM --direction right --n-items 6
    python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona WF --direction left \\
        --n-items 10 --runs 5 --baseline-runs 0 --verbose

Cost: about 1 min per greedy step on 4 cores with --pool 120 (random steps are ~instant).
Run one case at a time; the native runtime is multi-threaded.

Candidate pool (documented approximation): the --pool non-pole items with the largest
max(rank |mu|, rank range) in the exact step-0 sweep (one_step_results/<persona>/). With
--pool 0 every non-pole item is re-scored each step (exact, ~4 min per step). --audit re-runs the
full sweep at the final state of greedy run 0 and records whether its choice is inside the pool.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
REF = ROOT / "assets" / "question_sets" / "personas" / "target_states.json"


def ensure_native_binding():
    """Build the bundled native LSM binding if it cannot be imported."""
    sys.path.insert(0, str(ROOT / "native" / "lsm_runtime" / "python"))
    try:
        import dtag_lsm  # noqa: F401
    except ImportError:
        print("Building native DTAG LSM binding (one time) ...", flush=True)
        subprocess.run(["bash", str(ROOT / "scripts" / "build_native_bindings.sh")], check=True)


def candidate_pool(persona, size):
    s = pd.read_csv(HERE / "one_step_results" / persona / "variable_summary.csv")
    s = s[~s.is_pole_item].copy()
    if size <= 0:
        return None  # every non-pole item
    score = np.minimum(s.expected_delta.abs().rank(ascending=False), s["range"].rank(ascending=False))
    return sorted(s.loc[score.sort_values().index[:size], "variable"])


def run_table(steps, J0):
    lines = [f"    {'step':>4}  {'item':<14} {'response':<34} {'p':>5}  {'dJ':>9}  {'J after':>9}",
             f"    {0:>4}  {'(start)':<14} {'':<34} {'':>5}  {'':>9}  {J0:>+9.5f}"]
    for r in steps:
        lines.append(f"    {r['step']:>4}  {r['variable']:<14} {str(r['answer'])[:34]:<34} {r['p_answer']:>5.2f}  "
                     f"{r['delta_I']:>+9.5f}  {r['J_after']:>+9.5f}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", choices=["CM", "WF"], required=True)
    ap.add_argument("--direction", choices=["right", "left"], required=True)
    ap.add_argument("--n-items", "--steps", dest="n_items", type=int, default=6,
                    help="number of items asked per run (run length)")
    ap.add_argument("--runs", type=int, default=3, help="greedy runs")
    ap.add_argument("--baseline-runs", type=int, default=30, help="random-item runs (0 to skip)")
    ap.add_argument("--pool", type=int, default=120, help="candidate pool size; 0 = all non-pole items")
    ap.add_argument("--seed", type=int, default=2018)
    ap.add_argument("--audit", action="store_true", help="full sweep at the end of greedy run 0")
    ap.add_argument("--verbose", action="store_true",
                    help="also print the top candidates and every possible response with P and dJ")
    ap.add_argument("--out", type=Path, default=HERE / "greedy_runs")
    a = ap.parse_args(argv)
    if a.n_items < 1:
        ap.error("--n-items must be >= 1")

    ensure_native_binding()
    from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model
    from optimizer.one_step_geometry import native_one_step, policy_run

    world = World(str(ensure_model("gss/gss_2018", None, download=True)), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(HERE / "results" / "native_cache"))
    state, dropped = world.valid(json.loads(REF.read_text())[a.persona]["state"])
    pool = candidate_pool(a.persona, a.pool)
    J0 = world.I(state) - world.I({})
    print(f"{a.persona} -> {a.direction} | {a.n_items} items per run | {a.runs} greedy + {a.baseline_runs} random runs"
          f" | pool: {len(pool) if pool else 'all'} non-pole items", flush=True)
    print(f"start state: {state}\nJ0 = {J0:+.5f}", flush=True)
    seed = a.seed + {"CM": 0, "WF": 100}[a.persona] + {"right": 0, "left": 10}[a.direction]
    rows, ends = [], {"greedy_mu": [], "random": []}

    for policy, n in (("greedy_mu", a.runs), ("random", a.baseline_runs)):
        for k in range(n):
            rng = np.random.default_rng([seed, k, policy == "random"])
            t0 = time.time()
            print(f"\n[{policy} run {k}]", flush=True)

            def log(r, policy=policy, t0=t0):
                dt = r["detail"]
                if a.verbose and policy == "greedy_mu":
                    print(f"    candidates ({'argmax' if a.direction == 'right' else 'argmin'} mu, "
                          f"{dt['n_candidates']} scored):")
                    for i, x in enumerate(dt["alternatives"], 1):
                        mark = "  <== chosen" if x["variable"] == r["variable"] else ""
                        print(f"      {i}. {x['variable']:<14} mu={x['expected_delta']:+.5f} P_up={x['P_up']:.2f} "
                              f"P_down={x['P_down']:.2f}{' one-sided' if x['one_sided'] else ''}{mark}")
                    print("    responses (P, dJ):")
                    for x in sorted(dt["answers"], key=lambda x: -x["p"]):
                        mark = "  <== drawn" if x["answer"] == r["answer"] else ""
                        print(f"      {x['answer']!r:<40} P={x['p']:.3f}  dJ={x['delta']:+.5f}{mark}")
                mu = "" if r["expected_delta"] is None else f"  mu={r['expected_delta']:+.5f}"
                print(f"  step {r['step']}/{a.n_items}  item={r['variable']}  response={r['answer']!r} "
                      f"(p={r['p_answer']:.2f})  J {dt['J_before']:+.5f} -> {r['J_after']:+.5f}{mu}"
                      f"  [{time.time() - t0:.0f}s]", flush=True)

            steps = policy_run(world, state, a.direction, a.n_items, rng, policy=policy, only=pool, on_step=log)
            cum_mu = 0.0
            for r in steps:
                cum_mu += r["expected_delta"] or 0.0
                rows.append({"persona": a.persona, "direction": a.direction, "policy": policy, "run": k,
                             **{x: y for x, y in r.items() if x != "detail"},
                             "J_expected": J0 + cum_mu if policy == "greedy_mu" else None})
            J_end = steps[-1]["J_after"] if steps else J0
            ends[policy].append(J_end)
            print(run_table(steps, J0), flush=True)
            exp = f"; expected J (J0 + sum mu) = {J0 + cum_mu:+.5f}" if policy == "greedy_mu" else ""
            print(f"  final J = {J_end:+.5f} (change {J_end - J0:+.5f}){exp}", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.persona}_{a.direction}_n{a.n_items}"
    df = pd.DataFrame(rows)
    df.to_csv(a.out / f"{tag}.csv", index=False)
    meta = {"persona": a.persona, "direction": a.direction, "state": state, "dropped": dropped,
            "n_items": a.n_items, "runs": a.runs, "baseline_runs": a.baseline_runs,
            "pool_size": len(pool) if pool else "all", "seed": seed, "J0": J0}
    if a.audit and a.runs:
        print("\naudit: full sweep (all non-pole items) at the final state of greedy run 0 ...", flush=True)
        g0 = df[(df.policy == "greedy_mu") & (df.run == 0)]
        full = native_one_step(world, {**state, **dict(zip(g0.variable, g0.answer))}, exclude_poles=True)
        key = "argmax_mu" if a.direction == "right" else "argmin_mu"
        meta["audit"] = {"full_sweep_choice": full.extremes[key]["variable"],
                         "full_sweep_mu": full.extremes[key]["expected_delta"],
                         "in_pool": pool is None or full.extremes[key]["variable"] in pool,
                         "n_full_candidates": full.meta["n_variables"]}
        print(f"audit: full-sweep choice {meta['audit']['full_sweep_choice']} "
              f"(mu={meta['audit']['full_sweep_mu']:+.5f}); in pool: {meta['audit']['in_pool']}", flush=True)
    (a.out / f"{tag}.json").write_text(json.dumps(meta, indent=2, default=str))

    print(f"\n== {a.persona} -> {a.direction}, {a.n_items} items: J0 = {J0:+.5f}")
    for policy, js in ends.items():
        if js:
            print(f"   {policy:<9} final J: {', '.join(f'{j:+.5f}' for j in js[:10])}"
                  f"{' ...' if len(js) > 10 else ''}  | mean {np.mean(js):+.5f} (change {np.mean(js) - J0:+.5f})")
    print(f"saved {a.out / (tag + '.csv')} and .json", flush=True)


if __name__ == "__main__":
    main()
