#!/usr/bin/env python3
"""Build a DTAG semantic map aligned to a native GSS LSM model.

The native model feature list is authoritative. The GSS codebook contributes
human-readable labels/question text where available. Every model feature is
retained in the output map, so model-map overlap is complete by construction.

Example:
  python3 scripts/build_gss_native_map.py \
    --model models/lsm/gss/gss_2018 \
    --codebook data/gss/codebooks/GSS_1972_2018_Codebook.pdf \
    --out maps/gss/gss_2018_map.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402

VAR_RE = re.compile(r"^\s*Variable:\s*([A-Za-z0-9_]+)\b", re.I)
LABEL_RE = re.compile(r"^\s*Label:\s*(.*)\s*$", re.I)
STOP_RE = re.compile(
    r"^\s*(Notes:|LABEL\s+VALUE|RESERVED\s+CODES:|TOTALS:|SUBTOTALS:)\b",
    re.I,
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).replace("\u00a0", " ")).strip()


def parse_codebook(path: Path) -> pd.DataFrame:
    rows: List[dict] = []
    cur_var = None
    cur_page = None
    in_label = False
    label_lines: List[str] = []

    def flush() -> None:
        nonlocal cur_var, cur_page, in_label, label_lines
        if cur_var is not None:
            rows.append({
                "variable_key": str(cur_var).lower(),
                "question_text": norm(" ".join(label_lines)),
                "codebook_page": cur_page,
            })
        cur_var = None
        cur_page = None
        in_label = False
        label_lines = []

    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.rstrip()
                m = VAR_RE.match(line)
                if m:
                    flush()
                    cur_var = m.group(1)
                    cur_page = page_num
                    continue

                if cur_var is None:
                    continue

                m = LABEL_RE.match(line)
                if m:
                    in_label = True
                    first = norm(m.group(1))
                    label_lines = [first] if first else []
                    continue

                if in_label:
                    if STOP_RE.match(line):
                        in_label = False
                        continue
                    if line.strip():
                        label_lines.append(line.strip())

    flush()

    if not rows:
        return pd.DataFrame(columns=["variable_key", "question_text", "codebook_page"])

    d = pd.DataFrame(rows)
    d["score"] = d["question_text"].fillna("").astype(str).str.len()
    return (
        d.sort_values(["variable_key", "score"], ascending=[True, False])
         .drop_duplicates("variable_key", keep="first")
         .drop(columns=["score"])
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--codebook", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-text-coverage", type=float, default=0.0)
    args = ap.parse_args()

    def resolve(x: str) -> Path:
        p = Path(x).expanduser()
        return p.resolve() if p.is_absolute() else (ROOT / p).resolve()

    model_path = resolve(args.model)
    codebook_path = resolve(args.codebook)
    out_path = resolve(args.out)

    if not codebook_path.is_file():
        raise SystemExit(f"Codebook not found: {codebook_path}")

    model = load_model(model_path, backend="native_lsm")
    features = [str(v) for v in model.feature_names]

    docs = parse_codebook(codebook_path)
    lookup = {
        str(r.variable_key).lower(): (str(r.question_text or ""), r.codebook_page)
        for r in docs.itertuples(index=False)
    }

    rows = []
    matched = 0
    for var in features:
        text, page = lookup.get(var.lower(), ("", ""))
        text = norm(text)
        if text:
            matched += 1
        rows.append({
            "variable": var,
            "question_text": text,
            "question_text_filled": text or var,
            "codebook_page": page,
            "source": "GSS codebook" if text else "native LSM feature name",
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)

    coverage = matched / max(1, len(features))
    print(f"Wrote: {out_path}")
    print(f"Model variables: {len(features)}")
    print(f"Codebook text matched: {matched}/{len(features)} = {coverage:.3f}")
    print("Model-map overlap: 1.000 by construction")

    if coverage < args.min_text_coverage:
        raise SystemExit(
            f"Semantic text coverage {coverage:.3f} < required {args.min_text_coverage:.3f}"
        )


if __name__ == "__main__":
    main()
