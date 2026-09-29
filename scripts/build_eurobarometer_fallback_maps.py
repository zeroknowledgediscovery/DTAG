#!/usr/bin/env python3
"""Build auditable fallback Eurobarometer maps for waves without codebooks.

Exact GESIS-codebook maps remain authoritative. This script is only for native
Eurobarometer models whose own codebook is unavailable.

Strategy
--------
1. Compare the target model's exact feature-name set with every wave that has
   both a native model and a codebook-derived map.
2. Rank donor waves by feature-set F1/Jaccard similarity.
3. For each target variable, copy semantics only from an exact same-name
   variable in a sufficiently similar donor wave.
4. Preserve provenance (donor ZA and similarity) on every copied row.
5. Leave unmatched variables as explicit native-name fallbacks.

This avoids pretending that a borrowed map is an exact wave-specific codebook.

Examples
--------
Report donor quality without writing maps:

  python3 scripts/build_eurobarometer_fallback_maps.py --report-only

Build all codebook-missing waves:

  python3 scripts/build_eurobarometer_fallback_maps.py --build

Inspect/build one wave:

  python3 scripts/build_eurobarometer_fallback_maps.py --za ZA8843 --report-only
  python3 scripts/build_eurobarometer_fallback_maps.py --za ZA8843 --build
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm" / "eurobarometer"
MAP_ROOT = ROOT / "maps" / "eurobarometer"
CODEBOOK_ROOT = ROOT / "data" / "eurobarometer" / "codebooks"
REPORT_PATH = ROOT / "outputs" / "eurobarometer_fallback_donor_report.csv"

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


def model_features(path: Path) -> List[str]:
    model = load_model(path, backend="native_lsm")
    return [str(x) for x in model.feature_names]


def similarity(target: set[str], donor: set[str]) -> dict:
    inter = len(target & donor)
    nt = len(target)
    nd = len(donor)
    target_cov = inter / max(1, nt)
    donor_cov = inter / max(1, nd)
    jaccard = inter / max(1, len(target | donor))
    f1 = (2.0 * inter / (nt + nd)) if (nt + nd) else 0.0
    return {
        "intersection": inter,
        "target_coverage": target_cov,
        "donor_coverage": donor_cov,
        "jaccard": jaccard,
        "f1": f1,
    }


def za_distance(a: str, b: str) -> int:
    return abs(int(a[2:]) - int(b[2:]))


def read_map(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "variable" not in df.columns:
        raise ValueError(f"Map has no variable column: {path}")
    return df


def donor_rankings(
    target_za: str,
    target_features: List[str],
    donor_features: Dict[str, List[str]],
) -> List[dict]:
    target_set = set(target_features)
    rows = []
    for donor_za, features in donor_features.items():
        s = similarity(target_set, set(features))
        rows.append(
            {
                "target_za": target_za,
                "donor_za": donor_za,
                **s,
                "za_distance": za_distance(target_za, donor_za),
            }
        )

    rows.sort(
        key=lambda r: (
            -r["f1"],
            -r["jaccard"],
            -r["target_coverage"],
            r["za_distance"],
            int(r["donor_za"][2:]),
        )
    )
    return rows


def donor_row_lookup(df: pd.DataFrame) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for _, row in df.iterrows():
        var = str(row.get("variable", "")).strip()
        if not var or var in out:
            continue
        out[var] = row.to_dict()
    return out


def semantic_strength(row: dict) -> int:
    q = str(row.get("question_text", "")).strip()
    label = str(row.get("variable_label", "")).strip()
    filled = str(row.get("question_text_filled", "")).strip()
    if q:
        return 3
    if label:
        return 2
    if filled and filled != str(row.get("variable", "")).strip():
        return 1
    return 0


def build_fallback_map(
    target_za: str,
    target_features: List[str],
    rankings: List[dict],
    donor_maps: Dict[str, pd.DataFrame],
    out_path: Path,
    *,
    min_donor_f1: float,
    max_donors: int,
    force: bool,
) -> dict:
    if out_path.exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists; refusing to overwrite without --force"
        )

    eligible = [
        r for r in rankings
        if r["f1"] >= min_donor_f1
    ][:max_donors]

    lookups = {
        r["donor_za"]: donor_row_lookup(donor_maps[r["donor_za"]])
        for r in eligible
    }

    rows = []
    copied = 0
    copied_qtext = 0
    copied_label = 0

    for var in target_features:
        chosen = None
        chosen_rank = None

        for rank in eligible:
            donor_za = rank["donor_za"]
            candidate = lookups[donor_za].get(var)
            if candidate is None:
                continue
            if semantic_strength(candidate) <= 0:
                continue
            chosen = candidate
            chosen_rank = rank
            break

        if chosen is None:
            rows.append(
                {
                    "variable": var,
                    "question_number": "",
                    "variable_label": "",
                    "question_text": "",
                    "question_text_filled": var,
                    "source": "native LSM source map (fallback unresolved)",
                    "source_page": "",
                    "za_id": target_za,
                    "fallback_donor_za": "",
                    "fallback_donor_f1": "",
                    "fallback_donor_jaccard": "",
                }
            )
            continue

        copied += 1
        qtext = str(chosen.get("question_text", "")).strip()
        label = str(chosen.get("variable_label", "")).strip()
        if qtext:
            copied_qtext += 1
        if label:
            copied_label += 1

        rows.append(
            {
                "variable": var,
                "question_number": str(chosen.get("question_number", "")).strip(),
                "variable_label": label,
                "question_text": qtext,
                "question_text_filled": (
                    qtext
                    or label
                    or str(chosen.get("question_text_filled", "")).strip()
                    or var
                ),
                "source": f"Eurobarometer fallback exact-name donor {chosen_rank['donor_za']}",
                "source_page": str(chosen.get("source_page", "")).strip(),
                "za_id": target_za,
                "fallback_donor_za": chosen_rank["donor_za"],
                "fallback_donor_f1": f"{chosen_rank['f1']:.6f}",
                "fallback_donor_jaccard": f"{chosen_rank['jaccard']:.6f}",
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)

    n = len(target_features)
    return {
        "target_za": target_za,
        "variables": n,
        "copied_semantics": copied,
        "copied_fraction": copied / max(1, n),
        "question_text": copied_qtext,
        "question_text_fraction": copied_qtext / max(1, n),
        "labels": copied_label,
        "label_fraction": copied_label / max(1, n),
        "best_donor": eligible[0]["donor_za"] if eligible else "",
        "best_donor_f1": eligible[0]["f1"] if eligible else 0.0,
        "best_donor_jaccard": eligible[0]["jaccard"] if eligible else 0.0,
        "eligible_donors": len(eligible),
        "out": str(out_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--za", default="", help="one target ZA; default is all codebook-missing models")
    ap.add_argument("--report-only", action="store_true", help="rank donor waves but do not write maps")
    ap.add_argument("--build", action="store_true", help="write fallback maps")
    ap.add_argument("--top", type=int, default=5, help="number of donor candidates shown in report")
    ap.add_argument(
        "--min-donor-f1",
        type=float,
        default=0.50,
        help="minimum feature-set F1 required before borrowing semantics",
    )
    ap.add_argument(
        "--max-donors",
        type=int,
        default=5,
        help="maximum ranked donor waves used to fill exact-name variables",
    )
    ap.add_argument("--force", action="store_true", help="overwrite an existing target map")
    args = ap.parse_args()

    if not args.report_only and not args.build:
        args.report_only = True

    models = discover_models()
    codebooks = discover_codebooks()
    maps = discover_maps()

    exact_donors = sorted(
        set(models) & set(codebooks) & set(maps),
        key=lambda z: int(z[2:]),
    )

    if args.za:
        targets = [normalize_za(args.za)]
        missing = [z for z in targets if z not in models]
        if missing:
            raise SystemExit(f"No native model for: {' '.join(missing)}")
    else:
        targets = sorted(
            set(models) - set(codebooks),
            key=lambda z: int(z[2:]),
        )

    print(f"native models:       {len(models)}")
    print(f"exact donor waves:   {len(exact_donors)}")
    print(f"fallback targets:    {len(targets)}")

    feature_cache: Dict[str, List[str]] = {}

    def feats(za: str) -> List[str]:
        if za not in feature_cache:
            feature_cache[za] = model_features(models[za])
        return feature_cache[za]

    donor_features = {za: feats(za) for za in exact_donors}
    donor_maps = {za: read_map(maps[za]) for za in exact_donors}

    report_rows = []
    rankings_by_target: Dict[str, List[dict]] = {}

    for target_za in targets:
        rankings = donor_rankings(target_za, feats(target_za), donor_features)
        rankings_by_target[target_za] = rankings

        print(f"\n== {target_za} ==")
        print(f"variables: {len(feats(target_za))}")
        for rank, row in enumerate(rankings[:args.top], start=1):
            print(
                f"  {rank}. {row['donor_za']} "
                f"F1={row['f1']:.3f} "
                f"J={row['jaccard']:.3f} "
                f"target_cov={row['target_coverage']:.3f} "
                f"overlap={row['intersection']}"
            )
            report_rows.append({"rank": rank, **row})

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(report_rows).to_csv(REPORT_PATH, index=False)
    print(f"\nDonor report: {REPORT_PATH}")

    if not args.build:
        return

    print("\n================ BUILD ================")
    build_rows = []
    for target_za in targets:
        out_path = MAP_ROOT / f"{target_za}_map.csv"
        try:
            stats = build_fallback_map(
                target_za,
                feats(target_za),
                rankings_by_target[target_za],
                donor_maps,
                out_path,
                min_donor_f1=args.min_donor_f1,
                max_donors=args.max_donors,
                force=args.force,
            )
        except FileExistsError as e:
            print(f"SKIP {target_za}: {e}")
            continue

        build_rows.append(stats)
        print(
            f"{target_za}: copied={stats['copied_semantics']}/{stats['variables']} "
            f"({stats['copied_fraction']:.3f}) "
            f"qtext={stats['question_text_fraction']:.3f} "
            f"best={stats['best_donor']} "
            f"F1={stats['best_donor_f1']:.3f}"
        )

    build_report = ROOT / "outputs" / "eurobarometer_fallback_build_report.csv"
    pd.DataFrame(build_rows).to_csv(build_report, index=False)
    print(f"\nBuild report: {build_report}")


if __name__ == "__main__":
    main()
