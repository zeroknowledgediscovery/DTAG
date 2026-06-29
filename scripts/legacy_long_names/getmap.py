#!/usr/bin/env python3
"""
Extract (variable -> question/label text) for GSS 2024 from:
  1) a GSS 2024 .dta file (variable list, optional variable labels)
  2) the GSS 2024 codebook PDF (Label blocks under each Variable)

Outputs: gss2024_variable_question_map.csv

Dependencies:
  pip install pandas pyreadstat pdfplumber

Usage:
  python gss2024_questions_from_codebook.py \
    --dta GSS2024.dta \
    --codebook_pdf "GSS 2024 Codebook.pdf" \
    --out gss2024_variable_question_map.csv
"""

import argparse
import re
from pathlib import Path

import pandas as pd
import pyreadstat
import pdfplumber


VAR_RE = re.compile(r"^\s*Variable:\s*([A-Za-z0-9_]+)\b")
LABEL_RE = re.compile(r"^\s*Label:\s*(.*)\s*$")
STOP_RE = re.compile(
    r"^\s*(Notes:|LABEL\s+VALUE|RESERVED\s+CODES:|TOTALS:|SUBTOTALS:)\b"
)

def normalize_space(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_codebook_pdf(pdf_path: Path) -> pd.DataFrame:
    rows = []
    cur_var = None
    in_label = False
    label_lines = []
    cur_page = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for pi, page in enumerate(pdf.pages):
            cur_page = pi + 1
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = raw_line.rstrip()

                mvar = VAR_RE.match(line)
                if mvar:
                    if cur_var and label_lines:
                        rows.append(
                            {
                                "variable": cur_var,
                                "question_text": normalize_space(" ".join(label_lines)),
                                "codebook_page": cur_page,
                            }
                        )
                    cur_var = mvar.group(1)
                    in_label = False
                    label_lines = []
                    continue

                if cur_var is None:
                    continue

                mlabel = LABEL_RE.match(line)
                if mlabel:
                    in_label = True
                    first = mlabel.group(1).strip()
                    label_lines = [first] if first else []
                    continue

                if in_label:
                    if STOP_RE.match(line):
                        in_label = False
                        continue
                    if line.strip():
                        label_lines.append(line.strip())

    if cur_var and label_lines:
        rows.append(
            {
                "variable": cur_var,
                "question_text": normalize_space(" ".join(label_lines)),
                "codebook_page": cur_page,
            }
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["variable"], keep="first")
    return df

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dta", required=True, type=Path)
    ap.add_argument("--codebook_pdf", required=True, type=Path, nargs="+")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    # Read .dta metadata
    _, meta = pyreadstat.read_dta(str(args.dta), metadataonly=True)
    dta_vars = set(meta.column_names)

    dta_labels = {}
    for v, lab in zip(meta.column_names, meta.column_labels):
        if isinstance(lab, str) and lab.strip():
            dta_labels[v] = normalize_space(lab)

    # Parse one or more PDFs and combine
    pdf_frames = []
    for pdf_path in args.codebook_pdf:
        pdf_frames.append(parse_codebook_pdf(pdf_path))

    pdf_map = pd.concat(pdf_frames, ignore_index=True) if pdf_frames else pd.DataFrame()
    if not pdf_map.empty:
        pdf_map = pdf_map.drop_duplicates(subset=["variable"], keep="first")

    # Merge: keep variables actually in the .dta
    out = pd.DataFrame({"variable": sorted(dta_vars)})
    out["dta_variable_label"] = out["variable"].map(dta_labels)

    if not pdf_map.empty:
        out = out.merge(pdf_map, how="left", on="variable")
    else:
        out["question_text"] = pd.NA
        out["codebook_page"] = pd.NA

    # Some variables may have no codebook Label block; fall back to .dta label if present
    out["question_text_filled"] = out["question_text"]
    mask = out["question_text_filled"].isna() | (out["question_text_filled"].astype(str).str.len() == 0)
    out.loc[mask, "question_text_filled"] = out.loc[mask, "dta_variable_label"]

    out.to_csv(args.out, index=False)
    print(f"Wrote: {args.out}")
    print(f"Vars in dta: {len(out)}")
    print(f"Matched codebook labels: {out['question_text'].notna().sum()}")

if __name__ == "__main__":
    main()
