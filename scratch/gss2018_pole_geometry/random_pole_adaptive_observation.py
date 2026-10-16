#!/usr/bin/env python3
"""GSS 2018 simulation: RANDOM pole null and FROZEN adaptive observation policy.

The 40-question pole is chosen without referencing political-group separation
or the downstream LSM index. A response-adaptive decision policy chooses
questions solely by uncertainty of the *next response*, not by predicted
movement in an ideology index. Its deterministic definition is written to
policy.json BEFORE any trajectories are simulated.

Usage from DTAG root:
  python scratch/gss2018_pole_geometry/random_pole_adaptive_observation.py \
      --persona CM --pole-items 40 --pool-size 12 --questions 5 \
      --starts 3 --draws 3 --seed 2018

Do not confuse simulated conditional index updates with attitude change in humans.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import get_states  # noqa: E402
from optimizer.bank import from_map  # noqa: E402
from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model, sha256  # noqa: E402
from optimizer.population import perturb  # noqa: E402
from optimizer.ideology_coordinates import empty_state_offset  # noqa: E402
from dtag_session import build_polar_geometry  # noqa: E402

POLICY_VERSION = "frozen_response_entropy_v1"
PROTECTED = ("partyid", "polviews")


def random_poles(possible: Mapping[str, list[str]], eligible: list[str], count: int, seed: int):
    """Random nominal left/right labels, INDEPENDENT of any persona or objective."""
    names = sorted(set(v for v in eligible if len(set(possible.get(v, []))) >= 2))
    if not 1 < count <= len(names):
        raise ValueError(f"Need 2 <= number of pole items <= {len(names)}")
    rng = random.Random(seed)
    selected = sorted(rng.sample(names, count))
    rows = []
    for name in selected:
        options = sorted(set(str(a) for a in possible[name]))
        left, right = rng.sample(options, 2)
        rows.append({"variable": name, "L": left, "R": right})
    return rows


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def response_entropy(dist: Mapping[str, float]):
    """Shannon entropy of an observed categorical distribution (nats)."""
    probabilities = [float(p) for p in dist.values() if float(p) > 0]
    mass = sum(probabilities)
    if mass <= 0 or not math.isfinite(mass):
        return float("-inf")
    return -sum((p/mass)*math.log(p/mass) for p in probabilities)


def decide_next(world, state: dict, remaining: list[str], *, mode="max_entropy"):
    """Frozen observation rule: no access to pole geometry or desired movement."""
    if mode != "max_entropy":
        raise ValueError(f"Unsupported observation rule: {mode}")
    if not remaining:
        return None, {}, float("nan")
    dists = world.dists(state, sorted(remaining))
    scored = [(response_entropy(dists.get(v, {})), v)
              for v in sorted(remaining)]
    # Lexicographic tie breaking independent of downstream value function.
    _, picked = min(scored, key=lambda item: (-item[0], item[1]))
    return picked, dists.get(picked, {}), response_entropy(dists.get(picked, {}))


def draw_answer(dist, rng):
    if not dist:
        raise ValueError("Cannot sample absent categorical response probabilities")
    names = sorted(dist)
    return rng.choices(names, weights=[dist[k] for k in names])[0]


def simulate_policy(world, state, pool, n_questions, seed, offset, policy="max_entropy"):
    state = dict(state)
    rng = random.Random(seed)
    remaining = list(pool)
    track = [{"step": 0, "question": None, "answer": None,
              "entropy": None, "I_raw": world.I(state)}]
    for step in range(1, min(n_questions, len(pool)) + 1):
        var, probs, entropy = decide_next(world, state, remaining, mode=policy)
        if not probs:
            raise ValueError(f"No response distribution for {var}")
        ans = draw_answer(probs, rng)
        state[var] = ans
        remaining.remove(var)
        track.append({"step": step, "question": var, "answer": ans,
                      "entropy": entropy, "I_raw": world.I(state)})
    for item in track:
        item["I_centered"] = item["I_raw"]-offset
    return track


def validate_frozen_policy(descriptor, possible):
    if descriptor.get("version") != POLICY_VERSION or descriptor.get("rule") != "max_entropy":
        raise ValueError("Not a supported frozen policy")
    pool = descriptor["candidate_pool"]
    if not pool or len(set(pool)) != len(pool):
        raise ValueError("Question pool empty or contains duplicates")
    if set(pool) & set(descriptor.get("pole_variables", [])):
        raise ValueError("Adaptive questions intersect random pole items")
    for var in pool:
        if len(possible.get(var, [])) < 2:
            raise ValueError(f"Unsupported question: {var}")
    return True


def bootstrap_means(values, seed, nboot=1000):
    """Bootstrap across distinct randomized initial states, NOT individual draws."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"mean": None, "lower": None, "upper": None}
    if len(values) == 1:
        return {"mean": float(values[0]), "lower": None, "upper": None}
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(nboot, len(values)), replace=True).mean(axis=1)
    return {"mean": float(values.mean()), "lower": float(np.quantile(means, .025)),
            "upper": float(np.quantile(means, .975))}


def experiment(args):
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    model = ensure_model("gss/gss_2018", None, download=not args.no_download)
    world = World(str(model), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(out / "cache"))
    original_poles = world.poles_summary()
    ref_states, _ = get_states(world)
    initial = ref_states[f"{args.persona}_rich"]
    available = from_map(world)
    opinion_names = sorted({q["id"] for q in available
                            if q["id"] not in PROTECTED and
                            len(world.ctx.possible.get(q["id"], [])) >= 2})
    if args.geometry == "random":
        pole_rows = random_poles(world.ctx.possible, opinion_names,
                                 args.pole_items, args.seed)
        pole_file = out / "random_pole.csv"
        write_csv(pole_file, pole_rows, ["variable", "R", "L"])
        # Preserve all model trees/mappings; only the measured geometry changes.
        random_geom = build_polar_geometry(world.ctx, str(pole_file))
        if not random_geom.enabled or len(random_geom.left_map) != args.pole_items:
            raise ValueError(f"Random pole construction failed: {random_geom.disable_reason}")
        world.g = random_geom
    else:
        pole_file = Path(world.g.path)
    offset = empty_state_offset(world)
    excluded = set(world.g.left_map) | set(initial) | set(PROTECTED)
    eligible = sorted(set(opinion_names) - excluded)
    if len(eligible) < args.pool_size:
        raise RuntimeError("Insufficient eligible askable items")
    pool = sorted(random.Random(args.seed+1).sample(eligible, args.pool_size))
    descriptor = {
        "version": POLICY_VERSION,
        "rule": "max_entropy",
        "model_key": "gss/gss_2018",
        "model_path": str(model),
        "map_sha256": sha256(Path(world.map_path)),
        "geometry": args.geometry,
        "pole_file": str(pole_file),
        "pole_sha256": sha256(pole_file),
        "pole_variables": sorted(world.g.left_map),
        "candidate_pool": pool,
        "max_questions": args.questions,
        "seed": args.seed,
        "protected": list(PROTECTED),
        "selection_objective": "Shannon entropy of next-response distribution",
        "conditioning": "all observed answers already in this simulated state",
        "tie_breaker": "lexical variable order",
        "note": "Not selected to achieve any particular sign or movement of ideology",
    }
    validate_frozen_policy(descriptor, world.ctx.possible)
    # Freeze policy and checksums before looking at index trajectories.
    (out / "frozen_policy.json").write_text(json.dumps(descriptor, indent=2))
    rows, grouped = [], []
    for start in range(args.starts):
        rng = random.Random(args.seed*100003 + start)
        perturbed = perturb(world, initial, rng, args.drop, args.resample, list(PROTECTED))
        traces = []
        for draw in range(args.draws):
            trace = simulate_policy(world, perturbed, pool, args.questions,
                                    args.seed*1000003 + start*503 + draw,
                                    offset)
            traces.append(trace)
            rows.extend({"start": start, "draw": draw, **x} for x in trace)
        starts = [trace[0]["I_centered"] for trace in traces]
        changes = [trace[-1]["I_centered"]-trace[0]["I_centered"]
                   for trace in traces]
        if max(starts)-min(starts) > 1e-9:
            raise AssertionError("Draws of a fixed initial state do not share I0")
        grouped.append({"start": start, "I0_centered": starts[0],
                        "mean_change": statistics.mean(changes),
                        "sd_across_draws": statistics.stdev(changes)
                        if len(changes) > 1 else None,
                        "share_up": sum(c>0 for c in changes)/len(changes),
                        "n_draws": len(changes)})
    write_csv(out / "trajectories.csv", rows,
              ["start", "draw", "step", "question", "answer", "entropy",
               "I_raw", "I_centered"])
    write_csv(out / "per_start.csv", grouped,
              ["start", "I0_centered", "mean_change", "sd_across_draws",
               "share_up", "n_draws"])
    changes = [r["mean_change"] for r in grouped]
    stats = bootstrap_means(changes, args.seed+2, nboot=args.bootstrap)
    summary = {
        "persona": args.persona,
        "geometry": args.geometry,
        "original_poles": original_poles,
        "random_or_original_pole_items": len(world.g.left_map),
        "I_empty": offset,
        "I_initial_unperturbed": world.I(initial),
        "I_initial_centered": world.I(initial)-offset,
        "states": args.starts, "draws_per_state": args.draws,
        "question_pool": len(pool), "questions_per_trajectory": args.questions,
        "selection_rule": descriptor["rule"],
        "empirical_mean_change_across_starts": stats,
        "share_start_states_mean_up": sum(v > 0 for v in changes)/len(changes),
        "share_start_states_mean_down": sum(v < 0 for v in changes)/len(changes),
        "policy_file": str(out / "frozen_policy.json"),
        "interpretation": "Descriptive simulated conditional-information updates",
        "disclaimer": "This policy does not optimize a directional political index",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [
        "# Frozen adaptive observation policy — native GSS 2018", "",
        f"Persona: {args.persona}. Geometry: {args.geometry}.",
        f"Pole items: {len(world.g.left_map)}. I(empty): {offset:+.6f}.",
        f"Initial centered I: {world.I(initial)-offset:+.6f}.",
        f"Frozen pool size: {len(pool)}. Questions/trajectory: {args.questions}.",
        f"Randomized states: {args.starts}; draws per state: {args.draws}.", "",
        "Policy: select the highest-entropy unanswered question, then sample",
        "a native LSM conditional response, and branch on that response.",
        "Index sign and change play NO role in question selection.", "",
        "## Observed descriptive displacement", "",
        f"Mean across starting states: {stats['mean']:+.6f}.",
        f"State-bootstrap 95% interval: {stats['lower']}, {stats['upper']}.",
        f"Share starting states with positive mean movement: "
        f"{summary['share_start_states_mean_up']:.3f}.",
        f"Share starting states with negative mean movement: "
        f"{summary['share_start_states_mean_down']:.3f}.", "",
        "See frozen_policy.json, trajectories.csv, per_start.csv and summary.json.",
        "No political direction was optimized, and no human subjects were contacted.",
        ""]
    (out / "REPORT.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--persona", choices=["CM", "WF"], default="CM")
    p.add_argument("--geometry", choices=["random", "canonical"], default="random")
    p.add_argument("--pole-items", type=int, default=40)
    p.add_argument("--pool-size", type=int, default=12)
    p.add_argument("--questions", type=int, default=5)
    p.add_argument("--starts", type=int, default=3)
    p.add_argument("--draws", type=int, default=3)
    p.add_argument("--seed", type=int, default=2018)
    p.add_argument("--drop", type=float, default=.1)
    p.add_argument("--resample", type=float, default=.1)
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--out", type=Path,
                   default=Path(__file__).parent / "results/random_poles_entropy_policy")
    p.add_argument("--no-download", action="store_true")
    args = p.parse_args(argv)
    if not 38 <= args.pole_items <= 45:
        p.error("random pole count must remain 38–45")
    if not 1 <= args.questions <= args.pool_size:
        p.error("question count must be within question pool")
    if args.starts < 1 or args.draws < 1:
        p.error("starts/draws must be positive")
    if not 0 <= args.drop <= 1 or not 0 <= args.resample <= 1:
        p.error("perturbation probabilities must be within [0,1]")
    return experiment(args)


if __name__ == "__main__":
    main()
