#!/usr/bin/env python3
"""Example multi-step runs: push CM / WF left and right with the greedy-mu policy.

For one persona and one direction: T steps; at each step re-enumerate the candidate
questions exactly (optimizer.one_step_geometry), ask argmax mu (right) / argmin mu (left),
draw the answer from the native P(a|s,v), update the state. Plus a random-question baseline
over the same candidate pool. Native GSS 2018, original 2018 poles, pole items never asked.

Candidate pool (documented approximation, to keep each step ~1 min): the --pool non-pole
variables with the largest max(rank |mu|, rank range) in the exact step-0 sweep
(one_step_results/<persona>/variable_summary.csv). --audit re-runs the FULL sweep at the
final state of trajectory 0 and records whether the full argmax/argmin is inside the pool.

    python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona CM --direction right
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model  # noqa: E402
from optimizer.one_step_geometry import native_one_step, policy_run  # noqa: E402

REF = HERE.parents[1] / "assets" / "question_sets" / "personas" / "target_states.json"


def candidate_pool(persona, size):
    s = pd.read_csv(HERE / "one_step_results" / persona / "variable_summary.csv")
    s = s[~s.is_pole_item].copy()
    score = np.minimum(s.expected_delta.abs().rank(ascending=False), s["range"].rank(ascending=False))
    return sorted(s.loc[score.sort_values().index[:size], "variable"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", choices=["CM", "WF"], required=True)
    ap.add_argument("--direction", choices=["right", "left"], required=True)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--runs", type=int, default=3, help="sampled greedy trajectories")
    ap.add_argument("--baseline-runs", type=int, default=30)
    ap.add_argument("--pool", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2018)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--out", type=Path, default=HERE / "greedy_runs")
    a = ap.parse_args()

    world = World(str(ensure_model("gss/gss_2018", None, download=False)), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(HERE / "results" / "native_cache"))
    state, _ = world.valid(json.loads(REF.read_text())[a.persona]["state"])
    pool = candidate_pool(a.persona, a.pool)
    seed = a.seed + {"CM": 0, "WF": 100}[a.persona] + {"right": 0, "left": 10}[a.direction]
    rows = []
    for policy, n in (("greedy_mu", a.runs), ("random", a.baseline_runs)):
        for k in range(n):
            rng = np.random.default_rng([seed, k, policy == "random"])
            t0 = time.time()

            def log(r, policy=policy, k=k, t0=t0):
                if policy == "greedy_mu":
                    print(f"  [{policy} run {k} step {r['step']}/{a.steps}, {time.time() - t0:.0f}s] ask {r['variable']} "
                          f"(mu={r['expected_delta']:+.5f}) -> {r['answer']!r} (p={r['p_answer']:.2f}) "
                          f"dJ={r['delta_I']:+.5f} J={r['J_after']:+.5f}", flush=True)
            for r in policy_run(world, state, a.direction, a.steps, rng, policy=policy, only=pool, on_step=log):
                rows.append({"persona": a.persona, "direction": a.direction, "policy": policy, "run": k, **r})
            print(f"{a.persona} {a.direction} {policy} run {k} J_T={rows[-1]['J_after']:+.5f}", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.persona}_{a.direction}"
    df = pd.DataFrame(rows)
    df.to_csv(a.out / f"{tag}.csv", index=False)
    meta = {"persona": a.persona, "direction": a.direction, "state": state, "steps": a.steps,
            "pool_size": len(pool), "seed": seed, "J0": world.I(state) - world.I({})}
    print(f"saved {a.out / (tag + '.csv')}", flush=True)
    if a.audit:
        print("audit: full sweep at final state of greedy run 0 ...", flush=True)
        g0 = df[(df.policy == "greedy_mu") & (df.run == 0)]
        final = {**state, **dict(zip(g0.variable, g0.answer))}
        full = native_one_step(world, final, exclude_poles=True)
        key = "argmax_mu" if a.direction == "right" else "argmin_mu"
        meta["audit"] = {"full_sweep_choice": full.extremes[key]["variable"],
                         "full_sweep_mu": full.extremes[key]["expected_delta"],
                         "in_pool": full.extremes[key]["variable"] in pool,
                         "n_full_candidates": full.meta["n_variables"]}
    (a.out / f"{tag}.json").write_text(json.dumps(meta, indent=2, default=str))
    print(json.dumps(meta.get("audit", {})), flush=True)


if __name__ == "__main__":
    main()
