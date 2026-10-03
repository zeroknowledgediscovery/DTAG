#!/usr/bin/env python3
"""Build native GSS DTAG maps for every installed GSS wave.

The native model feature list is authoritative. Semantic text is resolved in
this order:

1. year-specific existing map (e.g. map2022.csv, map2024.csv);
2. cumulative GSS 1972-2018 codebook;
3. exact-name donor from nearby existing GSS maps;
4. native feature name fallback.

The cumulative codebook is parsed once, so all 35 maps can be generated in one
run without reopening the 38 MB PDF for every wave.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_gss_native_map import parse_codebook, norm  # noqa: E402
from model_backend import load_model  # noqa: E402
from dtag_paths import model_path  # noqa: E402


def year_from_name(name: str) -> int:
    m = re.search(r"(19|20)\d{2}", name)
    if not m:
        raise ValueError(f"Cannot extract GSS year from {name}")
    return int(m.group(0))


def read_semantic_map(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if "variable" not in df.columns:
        return {}
    text_col = next(
        (c for c in ("question_text_filled", "question_text", "variable_label") if c in df.columns),
        None,
    )
    if not text_col:
        return {}
    return {
        str(r["variable"]).lower(): str(r[text_col]).strip()
        for _, r in df.iterrows()
        if str(r["variable"]).strip() and str(r[text_col]).strip()
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model-root",
        default=str(model_path("gss")),
        help="directory containing gss_YYYY native model directories",
    )
    ap.add_argument(
        "--codebook",
        default="data/gss/codebooks/GSS_1972_2018_Codebook.pdf",
    )
    ap.add_argument("--outdir", default="maps/gss")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    def rp(x: str) -> Path:
        p = Path(x).expanduser()
        return p if p.is_absolute() else ROOT / p

    model_root = rp(args.model_root)
    codebook = rp(args.codebook)
    outdir = rp(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if not codebook.is_file():
        raise SystemExit(f"GSS codebook not found: {codebook}")

    models = sorted(
        p for p in model_root.iterdir()
        if p.is_dir() and re.fullmatch(r"gss_\d{4}", p.name)
    )
    if not models:
        raise SystemExit(f"No gss_YYYY native model directories under {model_root}")

    print(f"Parsing cumulative codebook once: {codebook}")
    docs = parse_codebook(codebook)
    codebook_lookup: Dict[str, Tuple[str, str]] = {}
    for r in docs.itertuples(index=False):
        key = str(r.variable_key).lower()
        txt = norm(str(r.question_text or ""))
        page = str(r.codebook_page or "")
        if txt:
            codebook_lookup[key] = (txt, page)

    existing_by_year: Dict[int, Dict[str, str]] = {}
    candidate_maps = {
        2018: outdir / "gss_2018_map.csv",
        2022: ROOT / "maps/map2022.csv",
        2024: ROOT / "maps/map2024.csv",
    }
    for year, p in candidate_maps.items():
        existing_by_year[year] = read_semantic_map(p)

    donor_years = sorted(y for y, m in existing_by_year.items() if m)

    print(f"native GSS models: {len(models)}")
    print(f"semantic donor years: {donor_years}")

    summary = []
    for model_dir in models:
        year = year_from_name(model_dir.name)
        out = outdir / f"gss_{year}_map.csv"

        if out.exists() and not args.force and year not in {2022, 2024}:
            print(f"SKIP {year}: {out} exists")
            continue

        model = load_model(model_dir, backend="native_lsm", preload=False)
        features = [str(x) for x in model.feature_names]

        year_specific = read_semantic_map(
            ROOT / f"maps/map{year}.csv"
        )
        if not year_specific and year in existing_by_year:
            year_specific = existing_by_year[year]

        rows = []
        counts = {
            "YEAR_SPECIFIC": 0,
            "GSS_CODEBOOK": 0,
            "DONOR_MAP": 0,
            "NATIVE_NAME": 0,
        }

        for var in features:
            key = var.lower()
            text = ""
            source = ""
            source_year = ""
            page = ""

            if key in year_specific:
                text = year_specific[key]
                source = "YEAR_SPECIFIC"
                source_year = str(year)
            else:
                cb = codebook_lookup.get(key)
                if cb and cb[0]:
                    text, page = cb
                    source = "GSS_CODEBOOK"
                else:
                    candidates = []
                    for dy in donor_years:
                        txt = existing_by_year.get(dy, {}).get(key, "")
                        if txt:
                            candidates.append((abs(dy - year), dy, txt))
                    if candidates:
                        _, dy, text = sorted(candidates)[0]
                        source = "DONOR_MAP"
                        source_year = str(dy)
                    else:
                        text = var
                        source = "NATIVE_NAME"

            counts[source] += 1
            rows.append(
                {
                    "variable": var,
                    "question_text": text,
                    "question_text_filled": text or var,
                    "source": source,
                    "source_year": source_year,
                    "codebook_page": page,
                    "map_provenance": source,
                }
            )

        pd.DataFrame(rows).to_csv(out, index=False)
        unresolved = counts["NATIVE_NAME"]
        resolved = len(features) - unresolved
        frac = resolved / max(1, len(features))
        print(
            f"GSS {year}: vars={len(features)} resolved={resolved} "
            f"({frac:.3f}) native_name={unresolved} -> {out}"
        )
        summary.append(
            {
                "year": year,
                "variables": len(features),
                "year_specific": counts["YEAR_SPECIFIC"],
                "gss_codebook": counts["GSS_CODEBOOK"],
                "donor_map": counts["DONOR_MAP"],
                "native_name": counts["NATIVE_NAME"],
                "resolved_fraction": frac,
                "out": str(out),
            }
        )

    report = ROOT / "outputs/gss_native_map_build_report.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summary).sort_values("year").to_csv(report, index=False)
    print(f"report: {report}")


if __name__ == "__main__":
    main()
