#!/usr/bin/env python3
"""Construct and audit DESCRIPTIVE GSS 2018 model-conditional reference poles.

This script does not optimize survey questions or select poles to produce any
desired persona sign. The poles are built from the native model's conditional
categorical response distributions under predeclared affiliation strata.

Run from DTAG root:
    python scratch/gss2018_pole_geometry/derive_stratified_poles.py
    python scratch/gss2018_pole_geometry/derive_stratified_poles.py \
        --stratify partyid --left "strong democrat" --right "strong republican" \
        --min-tv 0.05 --pool canonical
    python scratch/gss2018_pole_geometry/derive_stratified_poles.py \
        --stratify polviews --left "extremely liberal" \
        --right "extremely conservative" --pool opinion --max-items 150

This is MODEL-IMPLIED, not a weighted estimate from observed GSS microdata.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from optimizer.dtag_bridge import (DEFAULT_POLES, World, canonical_map,
                                    ensure_model, sha256)  # noqa: E402
from audit import (ANCHOR_ORDER, get_states, index, read_csv, write_csv)  # noqa: E402

MODEL_KEY = "gss/gss_2018"
BASELINE = ROOT / "assets/polar_vectors/gss/gss_2018_polar_vectors.csv"
EXCLUDE = {"polviews", "partyid"}


def categorical_mode(distribution):
    """Categorical expectation is a distribution; the mode is a hard-state proxy."""
    if not distribution:
        raise ValueError("empty distribution")
    total = sum(float(v) for v in distribution.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("non-normalizable conditional distribution")
    probs = {str(k): float(p) / total for k, p in distribution.items()}
    if any((not math.isfinite(v) or v < 0) for v in probs.values()):
        raise ValueError("invalid conditional probabilities")
    name = sorted(probs, key=lambda k: (-probs[k], k))[0]
    return name, probs[name], probs


def total_variation(left, right):
    labels = set(left) | set(right)
    return .5 * sum(abs(left.get(label, 0.) - right.get(label, 0.))
                    for label in labels)


def response_pool(world, kind="canonical", max_items=None, fixed=None):
    """Preselected pool, independent of observed modes and validation metrics."""
    fixed = set(fixed or {})
    if kind == "canonical":
        names = [r["variable"] for r in read_csv(BASELINE)]
    elif kind == "opinion":
        from optimizer.bank import from_map
        names = [r["id"] for r in from_map(world)]
    else:
        raise ValueError(f"Unknown pool {kind}")
    names = [v for v in names
             if v not in EXCLUDE and v not in fixed and
             v in world.ctx.idx_map and world.ctx.possible.get(v)]
    names = list(dict.fromkeys(names))
    if max_items is not None:
        names = names[:max_items]
    if not names:
        raise RuntimeError("No eligible model variables after restrictions")
    return names


def group_dists(world, conditioned, variables, batch_size=16):
    """Exact native LSM conditional marginals; no independent fake respondents."""
    all_dists = {}
    for start in range(0, len(variables), batch_size):
        chunk = variables[start:start+batch_size]
        all_dists.update(world.dists(conditioned, chunk))
        print(f"  conditional model marginals: {min(start + batch_size, len(variables))}/"
              f"{len(variables)} for {conditioned}", flush=True)
    return all_dists


def construct_poles(left_dists, right_dists, variables, *,
                    min_tv=.05, min_modal_prob=0.0, construction="contrast"):
    """Pick modal answers only when distinct; never condition on validation signs."""
    if not 0 <= min_tv <= 1 or not 0 <= min_modal_prob <= 1:
        raise ValueError("thresholds must lie in [0,1]")
    if construction not in ("contrast", "modal"):
        raise ValueError(f"Unknown pole construction: {construction}")
    L, R, audit = {}, {}, []
    for variable in variables:
        ld, rd = left_dists.get(variable), right_dists.get(variable)
        if not ld or not rd:
            audit.append({"variable": variable, "included": False,
                          "reason": "missing_model_conditional"})
            continue
        lv, lp, l_probs = categorical_mode(ld)
        rv, rp, r_probs = categorical_mode(rd)
        tv = total_variation(l_probs, r_probs)
        margin_l = (lp - sorted(l_probs.values(), reverse=True)[1]
                    if len(l_probs) > 1 else lp)
        margin_r = (rp - sorted(r_probs.values(), reverse=True)[1]
                    if len(r_probs) > 1 else rp)
        labels = sorted(set(l_probs) | set(r_probs))
        differences = {label: l_probs.get(label, 0.) - r_probs.get(label, 0.)
                       for label in labels}
        if construction == "contrast" and labels:
            # Responses that are most overrepresented in the reference stratum,
            # NOT whichever response is individually most common.
            chosen_left = sorted(labels, key=lambda k: (-differences[k], k))[0]
            chosen_right = sorted(labels, key=lambda k: (differences[k], k))[0]
            selected_left_prob = l_probs.get(chosen_left, 0.)
            selected_right_prob = r_probs.get(chosen_right, 0.)
        else:
            chosen_left, chosen_right = lv, rv
            selected_left_prob, selected_right_prob = lp, rp
        keep = (chosen_left != chosen_right and tv >= min_tv
                and selected_left_prob >= min_modal_prob
                and selected_right_prob >= min_modal_prob)
        reason = ("retained" if keep else
                  "below_min_tv" if tv < min_tv else
                  "same_modal_response" if chosen_left == chosen_right else
                  "below_selected_probability")
        audit.append({
            "variable": variable, "included": keep, "reason": reason,
            "construction": construction,
            "left_modal": lv, "right_modal": rv,
            "left_modal_probability": round(lp, 8),
            "right_modal_probability": round(rp, 8),
            "left_selected": chosen_left, "right_selected": chosen_right,
            "left_selected_probability": round(selected_left_prob, 8),
            "right_selected_probability": round(selected_right_prob, 8),
            "left_selected_excess": round(differences.get(chosen_left, 0.), 8),
            "right_selected_excess": round(-differences.get(chosen_right, 0.), 8),
            "left_mode_margin": round(margin_l, 8),
            "right_mode_margin": round(margin_r, 8),
            "tv_distance": round(tv, 8),
            "left_distribution": json.dumps(l_probs, sort_keys=True),
            "right_distribution": json.dumps(r_probs, sort_keys=True),
        })
        if keep:
            L[variable], R[variable] = chosen_left, chosen_right
    return L, R, audit


def pole_rows(L, R):
    if set(L) != set(R):
        raise ValueError("pole sides differ")
    return [{"variable": var, "R": R[var], "L": L[var]} for var in sorted(L)]


def fixed_assignments(world, raw):
    assignment = {}
    for text in raw:
        name, sep, value = text.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name or not value:
            raise ValueError(f"Invalid --fixed {text!r}; use VARIABLE=RESPONSE_LABEL")
        if name in assignment or name in EXCLUDE:
            raise ValueError(f"Invalid or duplicated fixed field: {name}")
        if value not in world.ctx.possible.get(name, []):
            raise ValueError(f"Unsupported {name}={value!r}; choices="
                             f"{world.ctx.possible.get(name, [])!r}")
        assignment[name] = value
    return assignment


def ordered_sweep(world, variants):
    """Independent anchor orientation: training variable explicitly marked."""
    rows, summaries = [], {}
    for variable, ordered in ANCHOR_ORDER.items():
        support = set(world.ctx.possible.get(variable, []))
        available = [(j, v) for j, v in enumerate(ordered) if v in support]
        summaries[variable] = {"expected": ordered,
                               "supported": [label for _, label in available],
                               "unsupported_expected": [v for v in ordered if v not in support],
                               "unranked_native_responses": sorted(support - set(ordered))}
        for name, (L, R) in variants.items():
            order_indices = []
            empty = index(world, {}, L, R)["index"]
            for ordinal, response in available:
                i = index(world, {variable: response}, L, R)["index"]
                rows.append({"variant": name, "variable": variable,
                             "orientation_rank": ordinal, "category": response,
                             "index": i, "I_minus_empty": i-empty,
                             "orientation_training_variable": variable == "partyid"})
                order_indices.append(i)
            pairs = len(order_indices) * (len(order_indices) - 1) // 2
            inversions = sum(order_indices[i] > order_indices[j]
                             for i in range(len(order_indices))
                             for j in range(i+1, len(order_indices)))
            summaries[variable][name] = {
                "n_tested": len(order_indices), "pairs": pairs,
                "monotonicity_inversions": inversions,
                "fraction_concordant": (1.0-inversions/pairs) if pairs else None,
                "first_to_last_delta": (order_indices[-1] - order_indices[0])
                                       if len(order_indices) >= 2 else None}
    return rows, summaries


def descriptive_diagnostics(world, variants, *, training_variable):
    states, invalid = get_states(world)
    comparisons = []
    for name, (L, R) in variants.items():
        empty = index(world, {}, L, R)["index"]
        # Moderate is held out if training is on partyid; do not use it to
        # choose answers or to optimize the pole.
        neutral_label = "moderate, middle of the road"
        centered = ({'polviews': neutral_label}
                    if neutral_label in world.ctx.possible.get("polviews", []) else None)
        center = index(world, centered, L, R)["index"] if centered is not None else None
        for persona, state in states.items():
            d = index(world, state, L, R)
            comparisons.append({"variant": name, "persona": persona,
                                "n_pole_variables": len(L),
                                "n_state_variables": len(state),
                                **d, "I_minus_empty": d["index"] - empty,
                                "I_minus_moderate": (d["index"] - center)
                                                    if center is not None else None})
    return comparisons, invalid


def inspect(args):
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    model_path = ensure_model(MODEL_KEY, None, download=not args.no_download)
    world = World(str(model_path), str(canonical_map(MODEL_KEY)),
                  str(DEFAULT_POLES), str(out / "native_cache"))
    support = world.ctx.possible.get(args.stratify, [])
    if args.stratify in ("partyid", "polviews"):
        left, right = args.left, args.right
        if left is None or right is None:
            defaults = (("strong democrat", "strong republican") if args.stratify == "partyid"
                        else ("extremely liberal", "extremely conservative"))
            left = left or defaults[0]
            right = right or defaults[1]
    else:
        raise ValueError("Stratification must be partyid or polviews")
    if left == right or left not in support or right not in support:
        raise ValueError(f"Invalid or identical stratum labels ({left!r}, {right!r}). "
                         f"Native labels for {args.stratify}: {support!r}")
    fixed = fixed_assignments(world, args.fixed)
    pool = response_pool(world, args.pool, args.max_items, fixed)
    left_state = {args.stratify: left, **fixed}
    right_state = {args.stratify: right, **fixed}
    print(f"Training on {args.stratify}: L={left!r}, R={right!r}; "
          f"fixed covariates={fixed!r}; pool={len(pool)}", flush=True)

    left_dists = group_dists(world, left_state, pool, args.batch_size)
    right_dists = group_dists(world, right_state, pool, args.batch_size)
    L, R, response_audit = construct_poles(left_dists, right_dists, pool,
                                           min_tv=args.min_tv,
                                           min_modal_prob=args.min_modal_prob,
                                           construction=args.construction)
    used_vars = set(L)
    print(f"Constructed {len(L)} paired, distinct modal answers from {len(pool)} "
          f"candidate variables", flush=True)

    # Check that the native representation exactly accepts every model-derived response.
    assert all(L[v] in world.ctx.possible[v] and R[v] in world.ctx.possible[v]
               and L[v] != R[v] for v in used_vars)
    file = out / "gss_2018_model_stratified_poles.csv"
    write_csv(file, pole_rows(L, R), ["variable", "R", "L"])
    columns = ["variable", "included", "reason", "construction",
               "left_modal", "right_modal",
               "left_modal_probability", "right_modal_probability",
               "left_selected", "right_selected",
               "left_selected_probability", "right_selected_probability",
               "left_selected_excess", "right_selected_excess",
               "left_mode_margin", "right_mode_margin", "tv_distance",
               "left_distribution", "right_distribution"]
    write_csv(out / "conditional_responses.csv", response_audit, columns)
    if len(L) < 2:
        raise RuntimeError(
            f"Only {len(L)} distinguishable modal pole pairs; "
            f"review {out / 'conditional_responses.csv'}. No adequate axis.")

    manualL, manualR = dict(world.g.left_map), dict(world.g.right_map)
    variants = {
        "model_stratified": (L, R),
        "manual_2018_v2": (manualL, manualR)}
    # Directly compare same columns to avoid mixing coverage with answer changes.
    common = sorted(set(L) & set(manualL))
    if len(common) >= 2:
        variants["model_stratified_shared_manual"] = (
            {v: L[v] for v in common}, {v: R[v] for v in common})
        variants["manual_shared_stratified"] = (
            {v: manualL[v] for v in common}, {v: manualR[v] for v in common})

    measurements, dropped = descriptive_diagnostics(
        world, variants, training_variable=args.stratify)
    sweep_rows, sweep_meta = ordered_sweep(world, variants)
    for row in sweep_rows:
        row["orientation_training_variable"] = row["variable"] == args.stratify
    write_csv(out / "persona_index_comparison.csv", measurements,
              ["variant", "persona", "n_pole_variables", "n_state_variables",
               "index", "d_left", "d_right", "d_LR", "numerator",
               "I_minus_empty", "I_minus_moderate"])
    write_csv(out / "anchor_orientation.csv", sweep_rows,
              ["variant", "variable", "orientation_rank", "category", "index",
               "I_minus_empty", "orientation_training_variable"])

    loo = []
    get_states_cached, _ = get_states(world)
    if not args.skip_loo:
        # Sensitivity check only. We do not drop poorly performing variables
        # to make any particular persona land on a desired sign.
        for var in sorted(L):
            smallL = {k: v for k, v in L.items() if k != var}
            smallR = {k: v for k, v in R.items() if k != var}
            if not smallL:
                continue
            for p in ("CM_core", "WF_core", "empty"):
                state = {} if p == "empty" else get_states_cached[p]
                base = index(world, state, L, R)["index"]
                changed = index(world, state, smallL, smallR)["index"]
                loo.append({"variable_removed": var, "persona": p,
                            "full_index": base, "without_index": changed,
                            "delta_index": changed-base})
    write_csv(out / "empirical_pole_leave_one_out.csv", loo,
              ["variable_removed", "persona", "full_index", "without_index", "delta_index"])

    summary = {
        "source": "Native LSM conditional categorical distributions, not raw respondent microdata",
        "model": MODEL_KEY, "model_path": str(model_path),
        "model_map_sha256": sha256(Path(world.map_path)),
        "model_pole_baseline_sha256": sha256(BASELINE),
        "training_strata": {"variable": args.stratify, "left": left, "right": right,
                            "identical_fixed_covariates": fixed},
        "design": {"candidate_pool": args.pool, "n_candidate_items": len(pool),
                   "min_tv": args.min_tv, "min_modal_prob": args.min_modal_prob,
                   "construction": args.construction,
                   "n_selected_items": len(L), "selected_variables": sorted(used_vars),
                   "n_shared_manual": len(common),
                   "withheld_anchor": "polviews" if args.stratify == "partyid" else "partyid"},
        "validation": {"anchor_sweeps": sweep_meta,
                       "persona_measurements": measurements,
                       "invalid_reference_assignments": dropped},
        "warning": "In-sample model-conditional diagnostic; not external held-out survey validation. "
                   "Do not infer real opinion movement or use for political persuasion."
    }
    (out / "results.json").write_text(json.dumps(summary, indent=2, default=str))
    report = [
        "# GSS 2018 model-stratified pole — descriptive audit", "",
        f"Reference variable: {args.stratify}, left={left}, right={right}.",
        f"Symmetrically fixed covariates: {fixed!r}.", "",
        f"Model-derived pole variables: **{len(L)}** of {len(pool)} eligible.",
        f"Hard pole construction: {args.construction}.",
        f"Overlap with manual v2: **{len(common)}**.",
        "This is categorical modal-response construction from native model",
        "conditional distributions, NOT observed 2018 respondent averages.",
        "Contrast mode picks the response most overrepresented in each",
        "stratum; it need not be either stratum's highest-frequency response.", "",
        "## Index comparison", "",
        "| Variant | Pairs | Empty | CM core | WF core | CM−WF |",
        "|---|---:|---:|---:|---:|---:|"]
    lookup = {(r["variant"], r["persona"]): r for r in measurements}
    for name, (lp, _) in variants.items():
        def get(p):
            return lookup.get((name, p), {}).get("index")
        empty, cm, wf = get("empty"), get("CM_core"), get("WF_core")
        report.append(
            f"| {name} | {len(lp)} | {empty:+.5f} | {cm:+.5f} | "
            f"{wf:+.5f} | {cm-wf:+.5f} |")
    report += ["", "## Independent anchor ordering", ""]
    for test_anchor in ANCHOR_ORDER:
        for variant in variants:
            entry = sweep_meta[test_anchor][variant]
            context = "(TRAINING ANCHOR; NOT INDEPENDENT)" if test_anchor == args.stratify else "(INDEPENDENT HELD-OUT ANCHOR)"
            report.append(
                f"- {test_anchor} {variant} {context}: "
                f"{entry['monotonicity_inversions']}/{entry['pairs']} "
                f"rank-order inversions; concordance={entry['fraction_concordant']}.")
    report += ["", "## Interpretation", "",
               "Correct opposite signs in the two example personas are neither required",
               "nor sufficient to establish pole validity.",
               "Evaluate held-out political-self-placement category ordering,",
               "reference population calibration, stability across question subsets",
               "and sensitivity to how categorical modes are chosen.",
               "Polviews and partyid are never part of the model-derived pole variables.",
               "No production pole files have been modified.", ""]
    (out / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Saved {file}; report {out/'REPORT.md'}", flush=True)
    for name in variants:
        key = sweep_meta["polviews" if args.stratify == "partyid" else "partyid"][name]
        print(f"{name}: independent anchor inversions "
              f"{key['monotonicity_inversions']}/{key['pairs']}", flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stratify", choices=["partyid", "polviews"], default="partyid")
    parser.add_argument("--left", help="left stratum response label")
    parser.add_argument("--right", help="right stratum response label")
    parser.add_argument("--fixed", action="append", default=[],
                        help="identical control assignment for both strata: name=value")
    parser.add_argument("--pool", choices=["canonical", "opinion"], default="canonical")
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument("--construction", choices=["contrast", "modal"],
                        default="contrast",
                        help="contrast picks largest conditional excess; modal picks group mode")
    parser.add_argument("--min-tv", type=float, default=.05)
    parser.add_argument("--min-modal-prob", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--skip-loo", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).parent / "results" / "model_stratified_partyid")
    args = parser.parse_args(argv)
    if args.max_items is not None and args.max_items < 2:
        parser.error("--max-items must be >=2")
    if args.batch_size < 1:
        parser.error("--batch-size must be >=1")
    inspect(args)


if __name__ == "__main__":
    main()
