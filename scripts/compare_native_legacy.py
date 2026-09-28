#!/usr/bin/env python3
"""Compare a legacy Quasinet DTAG model with a native LSM model.

This is a migration diagnostic, not a requirement that the two independently
trained models be identical. It quantifies how much DTAG-relevant behavior
changes when the backend/model is replaced.

The script uses shared feature names and shared categorical labels to generate
the same conditioning states for both models, then compares:
  - conditional distributions (Jensen-Shannon divergence)
  - argmax response agreement
  - qdistance geometry on matched state pairs
  - optional GSS ideology index when a polar-vector CSV is supplied
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from model_backend import load_model
import pipeline as core


def normalize_dist(d: Dict[str, float]) -> Dict[str, float]:
    out = {str(k): max(0.0, float(v)) for k, v in d.items() if np.isfinite(float(v))}
    z = sum(out.values())
    if z <= 0:
        return {}
    return {k: v / z for k, v in out.items()}


def js_divergence_bits(a: Dict[str, float], b: Dict[str, float]) -> float:
    p = normalize_dist(a)
    q = normalize_dist(b)
    keys = sorted(set(p) | set(q))
    if not keys:
        return float("nan")
    pv = np.array([p.get(k, 0.0) for k in keys], dtype=float)
    qv = np.array([q.get(k, 0.0) for k in keys], dtype=float)
    m = 0.5 * (pv + qv)

    def kl(x, y):
        mask = x > 0
        return float(np.sum(x[mask] * np.log2(x[mask] / y[mask])))

    return 0.5 * (kl(pv, m) + kl(qv, m))


def state_for(model, assignments: Dict[str, str]) -> np.ndarray:
    idx = {str(v): i for i, v in enumerate(model.feature_names)}
    row = np.array([""] * len(model.feature_names), dtype=object)
    for var, value in assignments.items():
        j = idx.get(var)
        if j is not None:
            row[j] = value
    return row


def shared_support(
    legacy,
    native,
) -> Tuple[Dict[str, List[str]], List[str]]:
    lp = legacy.possible_values()
    npv = native.possible_values()
    common = sorted(set(legacy.feature_names) & set(native.feature_names))
    support: Dict[str, List[str]] = {}
    for var in common:
        vals = sorted(set(map(str, lp.get(var, []))) & set(map(str, npv.get(var, []))))
        if vals:
            support[var] = vals
    return support, common


def summarize(xs: Sequence[float]) -> Dict[str, float | int | None]:
    arr = np.asarray([x for x in xs if np.isfinite(x)], dtype=float)
    if not len(arr):
        return {"n": 0, "mean": None, "median": None, "p95": None, "max": None}
    return {
        "n": int(len(arr)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "p95": float(np.quantile(arr, 0.95)),
        "max": float(np.max(arr)),
    }


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    pairs = [(a, b) for a, b in zip(x, y) if np.isfinite(a) and np.isfinite(b)]
    if len(pairs) < 2:
        return None
    a = np.asarray([p[0] for p in pairs], dtype=float)
    b = np.asarray([p[1] for p in pairs], dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True, help="legacy Quasinet model")
    ap.add_argument("--native", required=True, help="native LSM model directory")
    ap.add_argument("--states", type=int, default=12)
    ap.add_argument("--targets", type=int, default=20)
    ap.add_argument("--assignments", type=int, default=12)
    ap.add_argument("--distance-pairs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--polar-vectors", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    legacy = load_model(args.legacy, backend="quasinet")
    native = load_model(args.native, backend="native_lsm")

    support, common_features = shared_support(legacy, native)
    conditioning_vars = [v for v, vals in support.items() if len(vals) >= 2]
    native_tree_names = {
        native.feature_names[i] for i in native.tree_ids if i < len(native.feature_names)
    }
    target_vars = [v for v in support if v in native_tree_names]

    if not conditioning_vars:
        raise SystemExit("No common variables with at least two shared categorical states.")
    if not target_vars:
        raise SystemExit("No common target variables with native LSM trees.")

    n_targets = min(args.targets, len(target_vars))
    target_vars = list(rng.choice(target_vars, size=n_targets, replace=False))

    assignments_list: List[Dict[str, str]] = []
    rows_legacy: List[np.ndarray] = []
    rows_native: List[np.ndarray] = []

    for _ in range(max(1, args.states)):
        nassign = min(args.assignments, len(conditioning_vars))
        vars_ = list(rng.choice(conditioning_vars, size=nassign, replace=False))
        assigns = {
            var: str(rng.choice(support[var]))
            for var in vars_
        }
        assignments_list.append(assigns)
        rows_legacy.append(state_for(legacy, assigns))
        rows_native.append(state_for(native, assigns))

    js: List[float] = []
    argmax_equal = 0
    compared = 0
    per_target: Dict[str, List[float]] = {v: [] for v in target_vars}

    for rl, rn in zip(rows_legacy, rows_native):
        ld = legacy.predict_distributions(rl, target_names=target_vars)
        nd = native.predict_distributions(rn, target_names=target_vars)
        for var in target_vars:
            a = normalize_dist(ld.get(var, {}))
            b = normalize_dist(nd.get(var, {}))
            if not a or not b:
                continue
            d = js_divergence_bits(a, b)
            if np.isfinite(d):
                js.append(d)
                per_target[var].append(d)
            compared += 1
            if max(a, key=a.get) == max(b, key=b.get):
                argmax_equal += 1

    distance_legacy: List[float] = []
    distance_native: List[float] = []
    npairs = min(args.distance_pairs, max(0, len(rows_legacy) * (len(rows_legacy) - 1) // 2))
    all_pairs = [(i, j) for i in range(len(rows_legacy)) for j in range(i + 1, len(rows_legacy))]
    if npairs and all_pairs:
        pick = rng.choice(len(all_pairs), size=npairs, replace=False)
        for k in np.atleast_1d(pick):
            i, j = all_pairs[int(k)]
            distance_legacy.append(legacy.qdistance(rows_legacy[i], rows_legacy[j]))
            distance_native.append(native.qdistance(rows_native[i], rows_native[j]))

    result = {
        "legacy": str(Path(args.legacy).resolve()),
        "native": str(Path(args.native).resolve()),
        "common_features": len(common_features),
        "common_features_with_shared_support": len(support),
        "conditioning_variables": len(conditioning_vars),
        "targets_compared": len(target_vars),
        "states": len(rows_legacy),
        "conditional_js_bits": summarize(js),
        "argmax_agreement": (argmax_equal / compared) if compared else None,
        "n_conditional_comparisons": compared,
        "qdistance": {
            "pairs": len(distance_legacy),
            "pearson": pearson(distance_legacy, distance_native),
            "legacy": summarize(distance_legacy),
            "native": summarize(distance_native),
            "mean_absolute_difference": (
                float(np.mean(np.abs(np.asarray(distance_legacy) - np.asarray(distance_native))))
                if distance_legacy else None
            ),
        },
        "per_target_js_mean": {
            var: (float(np.mean(vals)) if vals else None)
            for var, vals in per_target.items()
        },
    }

    if args.polar_vectors:
        left, right = core.load_polar_vectors_csv(args.polar_vectors)
        common_polar_left = {
            v: str(val)
            for v, val in left.items()
            if v in support and str(val) in support[v]
        }
        common_polar_right = {
            v: str(val)
            for v, val in right.items()
            if v in support and str(val) in support[v]
        }
        usable = sorted(set(common_polar_left) & set(common_polar_right))
        lmap = {v: common_polar_left[v] for v in usable}
        rmap = {v: common_polar_right[v] for v in usable}

        lL = state_for(legacy, lmap)
        lR = state_for(legacy, rmap)
        nL = state_for(native, lmap)
        nR = state_for(native, rmap)
        dlr_l = legacy.qdistance(lL, lR)
        dlr_n = native.qdistance(nL, nR)

        il: List[float] = []
        inn: List[float] = []
        for rl, rn in zip(rows_legacy, rows_native):
            if dlr_l > 0 and dlr_n > 0:
                il.append((legacy.qdistance(lL, rl) - legacy.qdistance(lR, rl)) / dlr_l)
                inn.append((native.qdistance(nL, rn) - native.qdistance(nR, rn)) / dlr_n)

        sign_agreement = None
        if il:
            sign_agreement = float(np.mean(np.sign(il) == np.sign(inn)))

        result["ideology"] = {
            "common_polar_variables": len(usable),
            "legacy_dLR": dlr_l,
            "native_dLR": dlr_n,
            "states": len(il),
            "pearson": pearson(il, inn),
            "mean_absolute_difference": (
                float(np.mean(np.abs(np.asarray(il) - np.asarray(inn)))) if il else None
            ),
            "sign_agreement": sign_agreement,
        }

    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
