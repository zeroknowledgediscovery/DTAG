#!/usr/bin/env python3
"""Discover two empirical survey poles directly from native-LSM qdistance.

The poles are k=2 medoids of a sampled respondent distance matrix.  K=3 is
computed only as a diagnostic.  Generic poles are semantically unlabeled:
P_minus/P_plus are a deterministic orientation, not political left/right.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_backend import load_model  # noqa: E402


def _state_hash(row: Sequence[str]) -> str:
    h = hashlib.sha1()
    for x in row:
        h.update(str(x).encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()


def _clean_value(value: object, allowed: Sequence[str]) -> Tuple[str, bool]:
    """Return (supported_value_or_blank, was_invalid_nonblank)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "", False
    s = str(value).strip()
    if not s or s.lower() in {"nan", "na", "n/a", "none"}:
        return "", False
    aset = set(allowed)
    if s in aset:
        return s, False

    # Common CSV round-trip of integer category labels.
    if s.endswith(".0") and s[:-2] in aset:
        return s[:-2], False

    # Safe case-insensitive recovery only when unique.
    matches = [a for a in allowed if a.lower() == s.lower()]
    if len(matches) == 1:
        return matches[0], False
    return "", True


def load_sample_states(
    data_path: Path,
    model,
    sample_size: int,
    seed: int,
    min_observed: int,
    oversample: int,
    exclude: Sequence[str],
) -> Tuple[np.ndarray, np.ndarray, Dict[str, object]]:
    header = pd.read_csv(data_path, nrows=0)
    model_names = list(model.feature_names)
    model_set = set(model_names)
    excluded = set(exclude)
    cols = [c for c in header.columns if c in model_set and c not in excluded]
    if not cols:
        raise RuntimeError("No CSV columns overlap the native model feature names.")

    # Survey waves are normally modest in row count; restrict columns before load.
    df = pd.read_csv(data_path, dtype=str, usecols=cols, low_memory=False).fillna("")
    if df.empty:
        raise RuntimeError(f"No rows in {data_path}")

    rng = np.random.default_rng(seed)
    candidate_n = min(len(df), max(sample_size, sample_size * max(1, oversample)))
    candidate_idx = rng.choice(len(df), size=candidate_n, replace=False)
    candidate = df.iloc[candidate_idx].copy()

    possible = model.possible_values()
    idx = {v: i for i, v in enumerate(model_names)}
    rows: List[np.ndarray] = []
    source_rows: List[int] = []
    observed_counts: List[int] = []
    invalid_nonblank = 0
    nonblank_total = 0
    invalid_examples: Dict[str, List[str]] = {}

    for source_row, rec in zip(candidate.index.tolist(), candidate.to_dict(orient="records")):
        state = np.asarray([""] * len(model_names), dtype=object)
        nobs = 0
        for v in cols:
            raw = rec.get(v, "")
            sraw = str(raw).strip()
            if sraw:
                nonblank_total += 1
            cleaned, invalid = _clean_value(raw, possible.get(v, []))
            if invalid:
                invalid_nonblank += 1
                bucket = invalid_examples.setdefault(v, [])
                if len(bucket) < 5 and sraw not in bucket:
                    bucket.append(sraw)
            if cleaned:
                state[idx[v]] = cleaned
                nobs += 1
        if nobs >= min_observed:
            rows.append(state)
            source_rows.append(int(source_row))
            observed_counts.append(nobs)

    if len(rows) < sample_size:
        raise RuntimeError(
            f"Only {len(rows)} candidate rows had >= {min_observed} supported responses; "
            f"need {sample_size}. Increase --oversample or lower --min-observed."
        )

    # Keep exactly m after validity filtering; the candidate order is already random.
    rows = rows[:sample_size]
    source_rows = source_rows[:sample_size]
    observed_counts = observed_counts[:sample_size]

    arr = np.stack(rows, axis=0)
    invalid_fraction = (invalid_nonblank / nonblank_total) if nonblank_total else 0.0

    # Variables that look identifier-like in the actual sampled states.
    high_card = []
    for v in cols:
        j = idx[v]
        vals = [str(x) for x in arr[:, j] if str(x)]
        if len(vals) < max(5, sample_size // 10):
            continue
        frac_unique = len(set(vals)) / len(vals)
        if frac_unique >= 0.50:
            high_card.append(
                {"variable": v, "n_observed": len(vals), "n_unique": len(set(vals)),
                 "fraction_unique": frac_unique}
            )
    high_card.sort(key=lambda x: float(x["fraction_unique"]), reverse=True)

    meta: Dict[str, object] = {
        "rows_in_data": int(len(df)),
        "overlap_columns": len(cols),
        "excluded_columns": sorted(excluded),
        "sampled_source_rows": source_rows,
        "observed_count_min": int(min(observed_counts)),
        "observed_count_median": float(np.median(observed_counts)),
        "observed_count_max": int(max(observed_counts)),
        "invalid_nonblank_values": int(invalid_nonblank),
        "nonblank_values_checked": int(nonblank_total),
        "invalid_nonblank_fraction": float(invalid_fraction),
        "invalid_examples": invalid_examples,
        "high_cardinality_variables": high_card[:30],
    }
    return arr, np.asarray(source_rows, dtype=int), meta


def pairwise_qdistance(model, states: np.ndarray) -> np.ndarray:
    n = len(states)
    D = np.zeros((n, n), dtype=np.float64)
    t0 = time.time()
    total = n * (n - 1) // 2
    done = 0
    next_report = 0.10
    for i in range(n):
        for j in range(i + 1, n):
            d = float(model.qdistance(states[i], states[j]))
            if not np.isfinite(d):
                raise RuntimeError(f"Non-finite qdistance for sampled rows {i}, {j}: {d}")
            D[i, j] = D[j, i] = d
            done += 1
        if total and done / total >= next_report:
            print(f"qdistance matrix: {done}/{total} pairs ({100.0 * done / total:.1f}%)")
            next_report += 0.10
    print(f"qdistance matrix complete in {time.time() - t0:.2f}s")
    return D


def _init_medoids(D: np.ndarray, k: int) -> np.ndarray:
    n = len(D)
    if not (1 < k <= n):
        raise ValueError("k must satisfy 1 < k <= n")

    # Start with the globally farthest pair, then farthest-first.
    a, b = np.unravel_index(int(np.argmax(D)), D.shape)
    medoids = [int(a)]
    if int(b) != int(a):
        medoids.append(int(b))
    while len(medoids) < k:
        nearest = np.min(D[:, medoids], axis=1)
        nearest[medoids] = -np.inf
        medoids.append(int(np.argmax(nearest)))
    return np.asarray(medoids[:k], dtype=int)


def pam(D: np.ndarray, k: int, max_iter: int = 100) -> Tuple[np.ndarray, np.ndarray]:
    """Small dependency-free k-medoids/PAM update loop on a precomputed metric."""
    medoids = _init_medoids(D, k)
    labels = np.argmin(D[:, medoids], axis=1)

    for _ in range(max_iter):
        old = medoids.copy()
        labels = np.argmin(D[:, medoids], axis=1)

        for c in range(k):
            members = np.where(labels == c)[0]
            if len(members) == 0:
                nearest = np.min(D[:, medoids], axis=1)
                nearest[medoids] = -np.inf
                medoids[c] = int(np.argmax(nearest))
                continue
            block = D[np.ix_(members, members)]
            medoids[c] = int(members[int(np.argmin(block.sum(axis=1)))])

        medoids = np.asarray(sorted(set(int(x) for x in medoids)), dtype=int)
        if len(medoids) < k:
            chosen = medoids.tolist()
            while len(chosen) < k:
                nearest = np.min(D[:, chosen], axis=1)
                nearest[chosen] = -np.inf
                chosen.append(int(np.argmax(nearest)))
            medoids = np.asarray(chosen, dtype=int)

        if np.array_equal(np.sort(old), np.sort(medoids)):
            break

    labels = np.argmin(D[:, medoids], axis=1)
    return medoids, labels


def silhouette_precomputed(D: np.ndarray, labels: np.ndarray) -> Tuple[float, np.ndarray]:
    n = len(D)
    uniq = np.unique(labels)
    if len(uniq) < 2:
        return 0.0, np.zeros(n, dtype=float)
    s = np.zeros(n, dtype=float)
    for i in range(n):
        own = labels[i]
        same = np.where(labels == own)[0]
        same = same[same != i]
        if len(same) == 0:
            s[i] = 0.0
            continue
        a = float(np.mean(D[i, same]))
        b = min(float(np.mean(D[i, np.where(labels == c)[0]])) for c in uniq if c != own)
        den = max(a, b)
        s[i] = 0.0 if den <= 0 else (b - a) / den
    return float(np.mean(s)), s


def cluster_summary(D: np.ndarray, medoids: np.ndarray, labels: np.ndarray) -> Dict[str, object]:
    sil, _ = silhouette_precomputed(D, labels)
    sizes = [int(np.sum(labels == c)) for c in range(len(medoids))]
    within = []
    for c in range(len(medoids)):
        members = np.where(labels == c)[0]
        if len(members) <= 1:
            within.append(0.0)
        else:
            block = D[np.ix_(members, members)]
            vals = block[np.triu_indices(len(members), 1)]
            within.append(float(np.mean(vals)) if len(vals) else 0.0)
    inter_medoid = [
        float(D[medoids[i], medoids[j]])
        for i in range(len(medoids))
        for j in range(i + 1, len(medoids))
    ]
    return {
        "k": int(len(medoids)),
        "medoid_sample_indices": [int(x) for x in medoids],
        "cluster_sizes": sizes,
        "silhouette": sil,
        "within_cluster_mean_distance": within,
        "medoid_pair_distances": inter_medoid,
    }


def orient_two_medoids(states: np.ndarray, medoids: np.ndarray) -> Tuple[int, int]:
    if len(medoids) != 2:
        raise ValueError("orientation requires exactly two medoids")
    a, b = int(medoids[0]), int(medoids[1])
    # Sign is semantic-free but deterministic for the exact medoid states.
    return (a, b) if _state_hash(states[a]) <= _state_hash(states[b]) else (b, a)


def write_outputs(
    outdir: Path,
    model,
    states: np.ndarray,
    source_rows: np.ndarray,
    D: np.ndarray,
    minus_idx: int,
    plus_idx: int,
    labels: np.ndarray,
    summary: Dict[str, object],
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    np.save(outdir / "distance_matrix.npy", D)

    names = list(model.feature_names)
    pminus = states[minus_idx]
    pplus = states[plus_idx]

    # Full empirical respondent medoids, preserving asymmetric missingness.
    medoids_df = pd.DataFrame([pminus, pplus], columns=names)
    medoids_df.insert(0, "pole", ["P_minus", "P_plus"])
    medoids_df.insert(1, "source_row", [int(source_rows[minus_idx]), int(source_rows[plus_idx])])
    medoids_df.to_csv(outdir / "medoids.csv", index=False)

    # DTAG's legacy polar-vector file requires symmetric variable pairs.
    rows = []
    for j, v in enumerate(names):
        lv, rv = str(pminus[j]), str(pplus[j])
        if lv and rv:
            rows.append({"variable": v, "L": lv, "R": rv})
    pd.DataFrame(rows, columns=["variable", "L", "R"]).to_csv(
        outdir / "polar_vectors.csv", index=False
    )

    # Score the discovery sample against the projected pole states actually
    # representable by polar_vectors.csv.
    shared = {r["variable"] for r in rows}
    idx = {v: i for i, v in enumerate(names)}
    sminus = np.asarray([""] * len(names), dtype=object)
    splus = np.asarray([""] * len(names), dtype=object)
    for v in shared:
        j = idx[v]
        sminus[j] = pminus[j]
        splus[j] = pplus[j]
    dpp = float(model.qdistance(sminus, splus))

    dminus = np.zeros(len(states), dtype=float)
    dplus = np.zeros(len(states), dtype=float)
    polar = np.zeros(len(states), dtype=float)
    for i, s in enumerate(states):
        if hasattr(model, "distances_to_state"):
            dm, dp = model.distances_to_state(sminus, splus, s)
        else:
            dm, dp = model.qdistance(sminus, s), model.qdistance(splus, s)
        dminus[i], dplus[i] = float(dm), float(dp)
        polar[i] = 0.0 if dpp <= 0 else (float(dm) - float(dp)) / dpp

    assign = pd.DataFrame({
        "sample_index": np.arange(len(states), dtype=int),
        "source_row": source_rows.astype(int),
        "cluster": labels.astype(int),
        "distance_to_P_minus": dminus,
        "distance_to_P_plus": dplus,
        "polar_index": polar,
        "observed_responses": np.sum(states != "", axis=1).astype(int),
    })
    assign.to_csv(outdir / "sample_assignments.csv", index=False)

    summary["production_poles"] = {
        "P_minus_sample_index": int(minus_idx),
        "P_plus_sample_index": int(plus_idx),
        "P_minus_source_row": int(source_rows[minus_idx]),
        "P_plus_source_row": int(source_rows[plus_idx]),
        "shared_pole_variables": int(len(rows)),
        "d_Pminus_Pplus_projected": dpp,
        "orientation": "deterministic state hash; no semantic/political meaning",
        "polar_index_formula": "(d(P_minus,x)-d(P_plus,x))/d(P_minus,P_plus)",
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover empirical DTAG poles with native-LSM qdistance.")
    ap.add_argument("--data", required=True, type=Path, help="CSV used for this survey/model wave")
    ap.add_argument("--model", required=True, type=Path, help="native LSM model directory")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--sample-size", type=int, default=256)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min-observed", type=int, default=10)
    ap.add_argument("--oversample", type=int, default=4)
    ap.add_argument("--exclude", nargs="*", default=[], help="feature names to omit from sampled states")
    ap.add_argument("--max-invalid-fraction", type=float, default=0.20)
    ap.add_argument("--no-k3", action="store_true", help="skip the k=3 diagnostic")
    args = ap.parse_args()

    if args.sample_size < 4:
        raise SystemExit("--sample-size must be >= 4")

    print(f"loading native model: {args.model}")
    model = load_model(args.model)

    states, source_rows, data_meta = load_sample_states(
        args.data,
        model,
        sample_size=args.sample_size,
        seed=args.seed,
        min_observed=args.min_observed,
        oversample=args.oversample,
        exclude=args.exclude,
    )
    invalid_fraction = float(data_meta["invalid_nonblank_fraction"])
    if invalid_fraction > args.max_invalid_fraction:
        raise RuntimeError(
            f"{invalid_fraction:.1%} of nonblank sampled CSV values were not in native model support; "
            "the data/model pair is probably mismatched. See invalid_examples in diagnostics."
        )

    print(
        f"sampled {len(states)} respondents; observed responses median="
        f"{data_meta['observed_count_median']}"
    )
    D = pairwise_qdistance(model, states)

    med2, lab2 = pam(D, 2)
    k2 = cluster_summary(D, med2, lab2)
    print(f"k=2 silhouette={k2['silhouette']:.4f} sizes={k2['cluster_sizes']}")

    summary: Dict[str, object] = {
        "data": str(args.data.resolve()),
        "model": str(args.model.resolve()),
        "sample_size": int(args.sample_size),
        "seed": int(args.seed),
        "data_diagnostics": data_meta,
        "k2": k2,
    }

    if not args.no_k3 and len(states) >= 6:
        med3, lab3 = pam(D, 3)
        k3 = cluster_summary(D, med3, lab3)
        summary["k3_diagnostic"] = k3
        delta = float(k3["silhouette"]) - float(k2["silhouette"])
        summary["k3_minus_k2_silhouette"] = delta
        print(f"k=3 silhouette={k3['silhouette']:.4f} sizes={k3['cluster_sizes']} delta={delta:+.4f}")

    minus_idx, plus_idx = orient_two_medoids(states, med2)
    write_outputs(
        args.out, model, states, source_rows, D,
        minus_idx=minus_idx, plus_idx=plus_idx, labels=lab2, summary=summary,
    )
    print(f"wrote pole discovery outputs to {args.out}")


if __name__ == "__main__":
    main()
