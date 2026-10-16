#!/usr/bin/env python3
"""Native GSS 2018 test of EMPTY-CENTERED ideology, using ONE fixed random sequence.

Does not select questions by any ideology outcome, evaluate multiple candidates,
or adjust ordering after observing responses. It reports raw vs centered using
the SAME trajectories so index movement remains mathematically unchanged.

python scratch/gss2018_pole_geometry/test_empty_centering.py --states 12 --draws 6
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import get_states  # noqa: E402
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model  # noqa: E402
from optimizer.simulate import Simulator  # noqa: E402
from optimizer.four_way_audit import analyze  # noqa: E402
from optimizer.ideology_coordinates import (  # noqa: E402
    COORDINATE, empty_state_offset, recenter_runs_and_trajectories)


def fixed_candidate(world, states, seed, length=10):
    forbidden = set(world.g.left_map) | set(world.g.right_map) | {"polviews", "partyid"}
    for p in states:
        forbidden.update(p["state"])
    pool = sorted(v for v in world.ctx.idx_map
                  if v not in forbidden and bool(world.text.get(v, "").strip())
                  and 2 <= len(world.ctx.possible.get(v, [])) <= 12)
    if len(pool) < length:
        raise RuntimeError(f"Only {len(pool)} eligible source questions; require {length}")
    chosen = random.Random(seed).sample(pool, length)
    return chosen, pool


def group_summary(analysis):
    rows = {}
    for name in ("positive", "negative"):
        gp = (analysis.get("groups") or {}).get(name) or {}
        rows[name] = {
            "n_states": gp.get("n_states"),
            "n_draws": gp.get("n_draws"),
            "movement": (gp.get("raw_change_ci") or {}).get("mean"),
            "95pct_ci": [
                (gp.get("raw_change_ci") or {}).get("low"),
                (gp.get("raw_change_ci") or {}).get("high")],
        }
    return rows


def experiment(args):
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    model = ensure_model("gss/gss_2018", None, download=not args.no_download)
    world_args = (str(model), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(out / "native_cache"))
    world = World(*world_args)
    offset = empty_state_offset(world)
    ref_states, rejected = get_states(world)
    # Baseline rich persona descriptions are fixed BEFORE any response simulation.
    people = []
    for ident in ("CM", "WF"):
        state = ref_states[f"{ident}_rich"]
        protected = {k: state[k] for k in ("polviews", "partyid")}
        raw = world.I(state)
        people.append({"id": ident, "state": state, "I0": raw,
                       "protected_values": protected,
                       "direction": 1 if raw > 0.005 else -1 if raw < -.005 else 0})
    questions, pool = fixed_candidate(world, people, args.seed, 10)
    with (out / "fixed_question_set.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["step", "question", "variables"])
        for step, variable in enumerate(questions, 1):
            writer.writerow([step, world.text[variable], variable])
    config = {"drop": .15, "resample": .15,
              "exclude_vars": sorted(set(questions) | set(world.g.left_map)
                                     | set(world.g.right_map) | {"polviews", "partyid"}),
              "core": ["polviews", "partyid"]}
    simulator = Simulator(world_args, config, args.workers)
    try:
        runs = simulator.make_runs(
            people, args.draws, args.seed+103,
            only_directed=False, states_per_persona=args.states,
            augment_count=4)
        original = np.asarray(
            simulator.simulate(runs, [[v] for v in questions],
                               mode="draw", trajectories=True), dtype=float)
    finally:
        simulator.close()
    centered_runs, centered = recenter_runs_and_trajectories(
        runs, original, offset)
    for name, paths, assigned, origin in (
        ("raw", original, runs, 0.),
        ("empty_centered", centered, centered_runs, offset)):
        folder = out / name
        folder.mkdir(exist_ok=True)
        np.savez_compressed(
            folder / "validation_trajectories.npz",
            trajectories=paths,
            initial_ideology=np.asarray([r[2] for r in assigned]),
            state_id=np.asarray([r[4] for r in assigned]),
            participant=np.asarray([r[0] for r in assigned]),
            empty_state_index=np.asarray(offset),
            index_origin_value=np.asarray(origin),
            index_coordinate=np.asarray(COORDINATE if name != "raw" else "raw_legacy"))
    a_raw, a_center = (
        analyze(out / "raw", seed=args.seed, nboot=args.bootstrap),
        analyze(out / "empty_centered", seed=args.seed, nboot=args.bootstrap))
    change_raw = original[:, -1] - original[:, 0]
    change_center = centered[:, -1] - centered[:, 0]
    max_difference = float(np.max(np.abs(change_raw-change_center)))
    if max_difference > 1e-10:
        raise AssertionError(f"Index changes not invariant to origin shift: {max_difference}")
    comparison = [
        {"persona": p["id"], "raw_I0": p["I0"],
         "I_empty": offset, "centered_I0": p["I0"]-offset,
         "protected": ["polviews", "partyid"]}
        for p in people]
    report = {
        "method": "single outcome-independent 10-question native model simulation",
        "index_coordinate": COORDINATE,
        "model": "gss/gss_2018",
        "poles": world.poles_summary(),
        "I_empty": offset,
        "question_sampling_seed": args.seed,
        "n_eligible_questions": len(pool),
        "selected_question_variables": questions,
        "n_requested_states_per_persona": args.states,
        "n_draws_per_start": args.draws,
        "n_simulated_trajectories": len(original),
        "protected_variables": ["polviews", "partyid"],
        "persona_starting_states": comparison,
        "raw_result": a_raw,
        "centered_result": a_center,
        "max_absolute_difference_in_raw_changes": max_difference,
        "note": "Raw group labels versus centered group labels may change. "
                "Neither direction nor effect is optimized; descriptive model behavior only.",
        "nonindependence": "These are simulated model responses, not human behavior."}
    (out / "result.json").write_text(json.dumps(report, indent=2, default=float))
    lines = [
        "# GSS 2018: independent fixed-sequence empty-state centering test", "",
        f"Model: native gss/gss_2018; current {world.poles_summary()['items']}-item pole.",
        f"I(empty) = {offset:+.7f}.",
        f"One prespecified seeded random sequence, 10 questions, {len(original)} stochastic trajectories.",
        "Protected persona anchors: polviews and partyid.", "",
        "| Persona | Raw I0 | Centered I0 |",
        "|---|---:|---:|"]
    lines += [f"| {p['persona']} | {p['raw_I0']:+.5f} | {p['centered_I0']:+.5f} |"
              for p in comparison]
    lines += ["", "## Descriptive movement after same sequence", "",
              "| Coordinate | Starting group | Distinct states | Mean raw change | 95% bootstrap CI |",
              "|---|---|---:|---:|---|"]
    for name, a in (("Raw", a_raw), ("Centered", a_center)):
        for group, stats in group_summary(a).items():
            ci = stats["95pct_ci"]
            ci_text = (f"[{ci[0]:+.5f}, {ci[1]:+.5f}]"
                       if None not in ci else "not available")
            movement = stats["movement"]
            lines.append(
                f"| {name} | {group} | {stats['n_states']} | "
                f"{movement:+.5f} | {ci_text} |" if movement is not None
                else f"| {name} | {group} | {stats['n_states']} | — | {ci_text} |")
    lines += ["", f"Raw-index posthoc category: {a_raw.get('observed_regime') or 'not established'}.",
              f"Centered-index posthoc category: {a_center.get('observed_regime') or 'not established'}.",
              f"Centered state-cluster interval support: {a_center['status']}.",
              f"Maximum displacement difference before/after centering: {max_difference:.3g}.",
              "", "Caveat: no sequence selection or tuning was performed.",
              "Any category is an observation in this one fixed-model experiment,",
              "not evidence of political persuasion in respondents.", ""]
    (out / "REPORT.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--states", type=int, default=12)
    p.add_argument("--draws", type=int, default=6)
    p.add_argument("--bootstrap", type=int, default=2000)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--seed", type=int, default=2018)
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent / "results" / "centered_2018_fixed_probe")
    p.add_argument("--no-download", action="store_true")
    args = p.parse_args(argv)
    experiment(args)


if __name__ == "__main__":
    main()
