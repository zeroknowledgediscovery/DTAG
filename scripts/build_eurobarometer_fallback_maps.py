#!/usr/bin/env python3
"""Build auditable Eurobarometer fallback maps from the union of exact maps.

Exact GESIS-codebook maps are authoritative.  This script handles only native
Eurobarometer models whose own codebook is unavailable.

The fallback is variable-level, not wave-level:

1. Build a semantic union from every model-specific map backed by a local GESIS
   codebook.
2. For each target variable, collect every exact same-name occurrence in that
   union.
3. If one semantic interpretation dominates across waves, use that consensus.
4. If meanings conflict, compare the target variable's categorical support with
   support in the candidate donor models and use a clearly better state match.
5. If ambiguity remains, keep the native variable name rather than guessing.

Generated fallback maps retain normal DTAG map columns and add provenance fields
showing how every variable was resolved.

Examples
--------
Inspect all missing-codebook waves without writing maps:

  python3 scripts/build_eurobarometer_fallback_maps.py --report-only

Build all missing-codebook maps:

  python3 scripts/build_eurobarometer_fallback_maps.py --build

Inspect/build one wave:

  python3 scripts/build_eurobarometer_fallback_maps.py --za ZA8843 --report-only
  python3 scripts/build_eurobarometer_fallback_maps.py --za ZA8843 --build
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm" / "eurobarometer"
MAP_ROOT = ROOT / "maps" / "eurobarometer"
CODEBOOK_ROOT = ROOT / "data" / "eurobarometer" / "codebooks"

UNION_REPORT = ROOT / "outputs" / "eurobarometer_semantic_union.csv"
BUILD_REPORT = ROOT / "outputs" / "eurobarometer_union_fallback_build_report.csv"
VARIABLE_REPORT = ROOT / "outputs" / "eurobarometer_union_fallback_variables.csv"

sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402


def normalize_za(value: str) -> str:
    s = str(value).strip().upper()
    if not s.startswith("ZA"):
        s = "ZA" + s
    if not re.fullmatch(r"ZA\d+", s):
        raise ValueError(f"Invalid ZA id: {value!r}")
    return "ZA" + s[2:].zfill(4)


def za_from_name(name: str) -> str | None:
    m = re.search(r"(ZA\d+)", str(name), flags=re.I)
    return normalize_za(m.group(1)) if m else None


def za_distance(a: str, b: str) -> int:
    return abs(int(a[2:]) - int(b[2:]))


def discover_models() -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    if not MODEL_ROOT.is_dir():
        return out
    for p in MODEL_ROOT.iterdir():
        if not p.is_dir():
            continue
        za = za_from_name(p.name)
        if za:
            out[za] = p.resolve()
    return out


def discover_codebooks() -> set[str]:
    out: set[str] = set()
    if not CODEBOOK_ROOT.is_dir():
        return out
    for p in CODEBOOK_ROOT.glob("ZA*_cdb.pdf"):
        za = za_from_name(p.name)
        if za:
            out.add(za)
    return out


def discover_maps() -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    if not MAP_ROOT.is_dir():
        return out
    for p in MAP_ROOT.glob("ZA*_map.csv"):
        za = za_from_name(p.name)
        if za:
            out[za] = p.resolve()
    return out


def read_map(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "variable" not in df.columns:
        raise ValueError(f"Map has no variable column: {path}")
    return df


def semantic_strength(row: dict) -> int:
    q = str(row.get("question_text", "")).strip()
    label = str(row.get("variable_label", "")).strip()
    filled = str(row.get("question_text_filled", "")).strip()
    var = str(row.get("variable", "")).strip()
    if q:
        return 3
    if label:
        return 2
    if filled and filled != var:
        return 1
    return 0


def normalize_text(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("\u00ad", "")
    s = re.sub(r"\bq(?:uestion)?[._ -]*\d+[a-z0-9_.-]*\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def semantic_key(row: dict) -> str:
    q = str(row.get("question_text", "")).strip()
    label = str(row.get("variable_label", "")).strip()
    filled = str(row.get("question_text_filled", "")).strip()
    var = str(row.get("variable", "")).strip()

    # Full wording is normally the most stable cross-wave semantic signal.
    for candidate in (q, label, filled):
        key = normalize_text(candidate)
        if key and key != normalize_text(var):
            return key
    return ""


def normalize_state(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalized_support(values: Iterable[str]) -> set[str]:
    return {
        x
        for x in (normalize_state(v) for v in values)
        if x
    }


def support_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_model_info(path: Path) -> tuple[List[str], Dict[str, set[str]]]:
    model = load_model(path, backend="native_lsm")
    features = [str(x) for x in model.feature_names]
    possible = model.possible_values()
    supports = {
        name: normalized_support(possible.get(name, []))
        for name in features
    }
    return features, supports


def choose_representative(
    occurrences: List[dict],
    target_za: str,
    *,
    support_first: bool = False,
) -> dict:
    if support_first:
        return sorted(
            occurrences,
            key=lambda x: (
                -float(x.get("support_similarity", 0.0)),
                -int(x.get("semantic_strength", 0)),
                za_distance(target_za, x["source_za"]),
                int(x["source_za"][2:]),
            ),
        )[0]

    return sorted(
        occurrences,
        key=lambda x: (
            -int(x.get("semantic_strength", 0)),
            za_distance(target_za, x["source_za"]),
            int(x["source_za"][2:]),
        ),
    )[0]


def build_union(
    exact_zas: List[str],
    maps: Dict[str, Path],
    model_supports: Dict[str, Dict[str, set[str]]],
) -> tuple[Dict[str, List[dict]], pd.DataFrame]:
    union: Dict[str, List[dict]] = defaultdict(list)

    for za in exact_zas:
        df = read_map(maps[za])
        supports = model_supports[za]

        for _, s in df.iterrows():
            row = s.to_dict()
            var = str(row.get("variable", "")).strip()
            if not var:
                continue

            # Only codebook-derived semantics enter the union.  A raw native
            # name fallback from an otherwise exact map must never propagate.
            source = str(row.get("source", "")).strip().lower()
            if "gesis" not in source:
                continue
            if semantic_strength(row) <= 0:
                continue

            key = semantic_key(row)
            if not key:
                continue

            union[var].append(
                {
                    "source_za": za,
                    "variable": var,
                    "question_number": str(row.get("question_number", "")).strip(),
                    "variable_label": str(row.get("variable_label", "")).strip(),
                    "question_text": str(row.get("question_text", "")).strip(),
                    "question_text_filled": str(row.get("question_text_filled", "")).strip(),
                    "source_page": str(row.get("source_page", "")).strip(),
                    "semantic_key": key,
                    "semantic_strength": semantic_strength(row),
                    "support": supports.get(var, set()),
                }
            )

    summary_rows: List[dict] = []
    for var, occurrences in sorted(union.items()):
        clusters: Dict[str, List[dict]] = defaultdict(list)
        for occ in occurrences:
            clusters[occ["semantic_key"]].append(occ)

        total = len(occurrences)
        ordered = sorted(
            clusters.items(),
            key=lambda kv: (
                -len(kv[1]),
                kv[0],
            ),
        )
        top_key, top_rows = ordered[0]
        rep = sorted(
            top_rows,
            key=lambda x: (
                -x["semantic_strength"],
                int(x["source_za"][2:]),
            ),
        )[0]

        summary_rows.append(
            {
                "variable": var,
                "n_occurrences": total,
                "n_semantic_clusters": len(clusters),
                "top_cluster_sources": len(top_rows),
                "top_cluster_fraction": len(top_rows) / max(1, total),
                "top_sources": ";".join(sorted({x["source_za"] for x in top_rows})),
                "representative_label": rep["variable_label"],
                "representative_question_text": rep["question_text"],
                "semantic_key": top_key,
            }
        )

    return union, pd.DataFrame(summary_rows)


def resolve_variable(
    variable: str,
    target_za: str,
    target_support: set[str],
    occurrences: List[dict],
    *,
    min_consensus_fraction: float,
    min_consensus_sources: int,
    min_support_similarity: float,
    support_margin: float,
) -> dict:
    if not occurrences:
        return {
            "resolution": "UNRESOLVED_NATIVE",
            "representative": None,
            "sources": [],
            "n_sources": 0,
            "consensus_fraction": 0.0,
            "support_similarity": 0.0,
            "candidate_occurrences": 0,
            "semantic_clusters": 0,
        }

    clusters: Dict[str, List[dict]] = defaultdict(list)
    for occ in occurrences:
        x = dict(occ)
        x["support_similarity"] = support_similarity(target_support, x["support"])
        clusters[x["semantic_key"]].append(x)

    total = sum(len(v) for v in clusters.values())
    ordered_by_count = sorted(
        clusters.items(),
        key=lambda kv: (
            -len(kv[1]),
            min(za_distance(target_za, x["source_za"]) for x in kv[1]),
            kv[0],
        ),
    )

    top_key, top_rows = ordered_by_count[0]
    top_fraction = len(top_rows) / max(1, total)

    if (
        len(top_rows) >= min_consensus_sources
        and top_fraction >= min_consensus_fraction
    ):
        rep = choose_representative(top_rows, target_za)
        return {
            "resolution": "UNION_CONSENSUS",
            "representative": rep,
            "sources": sorted({x["source_za"] for x in top_rows}),
            "n_sources": len({x["source_za"] for x in top_rows}),
            "consensus_fraction": top_fraction,
            "support_similarity": max(
                float(x.get("support_similarity", 0.0)) for x in top_rows
            ),
            "candidate_occurrences": total,
            "semantic_clusters": len(clusters),
        }

    # Ambiguous semantics: score each semantic cluster by its strongest
    # categorical-state match to the target model.
    cluster_scores = []
    for key, rows in clusters.items():
        best = max(float(x.get("support_similarity", 0.0)) for x in rows)
        cluster_scores.append((best, key, rows))

    cluster_scores.sort(
        key=lambda x: (
            -x[0],
            -len(x[2]),
            min(za_distance(target_za, y["source_za"]) for y in x[2]),
            x[1],
        )
    )

    best_score, _, best_rows = cluster_scores[0]
    second_score = cluster_scores[1][0] if len(cluster_scores) > 1 else 0.0

    if (
        best_score >= min_support_similarity
        and (
            len(cluster_scores) == 1
            or best_score - second_score >= support_margin
        )
    ):
        rep = choose_representative(best_rows, target_za, support_first=True)
        return {
            "resolution": "UNION_SUPPORT_MATCH",
            "representative": rep,
            "sources": sorted({x["source_za"] for x in best_rows}),
            "n_sources": len({x["source_za"] for x in best_rows}),
            "consensus_fraction": len(best_rows) / max(1, total),
            "support_similarity": best_score,
            "candidate_occurrences": total,
            "semantic_clusters": len(clusters),
        }

    return {
        "resolution": "UNRESOLVED_NATIVE",
        "representative": None,
        "sources": [],
        "n_sources": 0,
        "consensus_fraction": top_fraction,
        "support_similarity": best_score,
        "candidate_occurrences": total,
        "semantic_clusters": len(clusters),
    }


def make_output_row(
    variable: str,
    target_za: str,
    resolved: dict,
) -> dict:
    resolution = resolved["resolution"]
    rep = resolved["representative"]

    if rep is None:
        return {
            "variable": variable,
            "question_number": "",
            "variable_label": "",
            "question_text": "",
            "question_text_filled": variable,
            "source": "native LSM source map (union fallback unresolved)",
            "source_page": "",
            "za_id": target_za,
            "map_provenance": "UNRESOLVED_NATIVE",
            "fallback_sources": "",
            "fallback_n_sources": resolved["n_sources"],
            "fallback_consensus_fraction": f"{resolved['consensus_fraction']:.6f}",
            "fallback_support_similarity": f"{resolved['support_similarity']:.6f}",
            "fallback_resolution": resolution,
            "fallback_candidate_occurrences": resolved["candidate_occurrences"],
            "fallback_semantic_clusters": resolved["semantic_clusters"],
        }

    qtext = rep["question_text"]
    label = rep["variable_label"]
    filled = qtext or label or rep["question_text_filled"] or variable

    return {
        "variable": variable,
        "question_number": rep["question_number"],
        "variable_label": label,
        "question_text": qtext,
        "question_text_filled": filled,
        "source": (
            "Eurobarometer semantic union consensus"
            if resolution == "UNION_CONSENSUS"
            else "Eurobarometer semantic union support match"
        ),
        "source_page": rep["source_page"],
        "za_id": target_za,
        "map_provenance": resolution,
        "fallback_sources": ";".join(resolved["sources"]),
        "fallback_n_sources": resolved["n_sources"],
        "fallback_consensus_fraction": f"{resolved['consensus_fraction']:.6f}",
        "fallback_support_similarity": f"{resolved['support_similarity']:.6f}",
        "fallback_resolution": resolution,
        "fallback_candidate_occurrences": resolved["candidate_occurrences"],
        "fallback_semantic_clusters": resolved["semantic_clusters"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--za", default="", help="one target ZA; default is all codebook-missing models")
    ap.add_argument("--report-only", action="store_true", help="resolve variables but do not write maps")
    ap.add_argument("--build", action="store_true", help="write fallback maps")
    ap.add_argument("--force", action="store_true", help="overwrite existing target fallback maps")
    ap.add_argument("--min-consensus-fraction", type=float, default=0.80)
    ap.add_argument("--min-consensus-sources", type=int, default=2)
    ap.add_argument("--min-support-similarity", type=float, default=0.75)
    ap.add_argument("--support-margin", type=float, default=0.15)
    args = ap.parse_args()

    if not args.report_only and not args.build:
        args.report_only = True

    models = discover_models()
    codebooks = discover_codebooks()
    maps = discover_maps()

    exact_zas = sorted(
        set(models) & set(codebooks) & set(maps),
        key=lambda z: int(z[2:]),
    )

    if args.za:
        targets = [normalize_za(args.za)]
        if targets[0] not in models:
            raise SystemExit(f"No native model for {targets[0]}")
        if targets[0] in codebooks:
            raise SystemExit(
                f"{targets[0]} has its own codebook; do not replace its exact map with fallback"
            )
    else:
        targets = sorted(
            set(models) - set(codebooks),
            key=lambda z: int(z[2:]),
        )

    print(f"native models:             {len(models)}")
    print(f"exact codebook/map waves:  {len(exact_zas)}")
    print(f"fallback targets:          {len(targets)}")

    feature_cache: Dict[str, List[str]] = {}
    support_cache: Dict[str, Dict[str, set[str]]] = {}

    def load_info(za: str) -> tuple[List[str], Dict[str, set[str]]]:
        if za not in feature_cache:
            features, supports = load_model_info(models[za])
            feature_cache[za] = features
            support_cache[za] = supports
        return feature_cache[za], support_cache[za]

    print("\nLoading exact-wave categorical support...")
    for za in exact_zas:
        load_info(za)

    union, union_report = build_union(exact_zas, maps, support_cache)
    UNION_REPORT.parent.mkdir(parents=True, exist_ok=True)
    union_report.to_csv(UNION_REPORT, index=False)

    print(f"union variable names:      {len(union)}")
    print(f"union index:               {UNION_REPORT}")

    build_rows: List[dict] = []
    variable_rows: List[dict] = []

    for target_za in targets:
        features, target_supports = load_info(target_za)
        output_rows = []
        counts = Counter()

        for variable in features:
            resolved = resolve_variable(
                variable,
                target_za,
                target_supports.get(variable, set()),
                union.get(variable, []),
                min_consensus_fraction=args.min_consensus_fraction,
                min_consensus_sources=args.min_consensus_sources,
                min_support_similarity=args.min_support_similarity,
                support_margin=args.support_margin,
            )
            counts[resolved["resolution"]] += 1
            output_rows.append(make_output_row(variable, target_za, resolved))
            variable_rows.append(
                {
                    "target_za": target_za,
                    "variable": variable,
                    "resolution": resolved["resolution"],
                    "fallback_sources": ";".join(resolved["sources"]),
                    "fallback_n_sources": resolved["n_sources"],
                    "fallback_consensus_fraction": resolved["consensus_fraction"],
                    "fallback_support_similarity": resolved["support_similarity"],
                    "candidate_occurrences": resolved["candidate_occurrences"],
                    "semantic_clusters": resolved["semantic_clusters"],
                }
            )

        n = len(features)
        resolved_n = (
            counts["UNION_CONSENSUS"]
            + counts["UNION_SUPPORT_MATCH"]
        )

        print(f"\n== {target_za} ==")
        print(f"variables:              {n}")
        print(f"UNION_CONSENSUS:        {counts['UNION_CONSENSUS']}")
        print(f"UNION_SUPPORT_MATCH:    {counts['UNION_SUPPORT_MATCH']}")
        print(f"UNRESOLVED_NATIVE:      {counts['UNRESOLVED_NATIVE']}")
        print(f"resolved fraction:      {resolved_n / max(1, n):.3f}")

        build_rows.append(
            {
                "target_za": target_za,
                "variables": n,
                "union_consensus": counts["UNION_CONSENSUS"],
                "union_support_match": counts["UNION_SUPPORT_MATCH"],
                "unresolved_native": counts["UNRESOLVED_NATIVE"],
                "resolved": resolved_n,
                "resolved_fraction": resolved_n / max(1, n),
            }
        )

        if args.build:
            out_path = MAP_ROOT / f"{target_za}_map.csv"
            if out_path.exists() and not args.force:
                raise SystemExit(
                    f"{out_path} already exists; use --force only if it is a prior fallback map"
                )
            pd.DataFrame(output_rows).to_csv(out_path, index=False)
            print(f"wrote:                  {out_path}")

    BUILD_REPORT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(build_rows).to_csv(BUILD_REPORT, index=False)
    pd.DataFrame(variable_rows).to_csv(VARIABLE_REPORT, index=False)

    print(f"\nsummary report:            {BUILD_REPORT}")
    print(f"variable report:           {VARIABLE_REPORT}")


if __name__ == "__main__":
    main()
