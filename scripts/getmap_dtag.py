#!/usr/bin/env python3
"""
getmap_dtag.py

Build a DTAG-ready variable -> question_text map for Afrobarometer merged surveys.

Why this exists:
- DTAG pipeline.py expects a CSV with columns: variable, question_text.
- Older Afrobarometer R1 codebooks use blocks beginning with "Variable name:" and
  country-specific "Question text - ..." fields.
- Newer Afrobarometer R2+ codebooks use blocks beginning with "Question Number:"
  followed by "Question:" and "Variable Label:" fields.
- The earlier getmap.py emitted variable,explanation with multiple rows per variable;
  that is useful for audit, but not ideal as a direct DTAG map.

Dependencies:
  pip install pandas pyreadstat pdfplumber

Examples:
  python getmap_dtag.py \
    --data afrobarometer_merged_data/merged_r2_data.sav \
    --codebook_pdf afrobarometer_merged_data/merged_r2_codebook2.pdf \
    --out maps/afrobarometer/merged_r2_map.csv

  python getmap_dtag.py \
    --data afrobarometer_merged_data/merged_r1_data.sav \
    --codebook_pdf afrobarometer_merged_data/merged_r1_codebook2.pdf \
    --out maps/afrobarometer/merged_r1_map.csv

Optional qnet alignment:
  python getmap_dtag.py \
    --data merged_r9_data.sav \
    --codebook_pdf merged_r9_codebook.pdf \
    --qnet models/afrobarometer/merged_r9_qnet.pkl.gz \
    --out maps/afrobarometer/merged_r9_map.csv
"""

from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import pdfplumber

try:
    import pyreadstat
except Exception:  # pragma: no cover
    pyreadstat = None


# -----------------------------
# Normalization / cleaning
# -----------------------------

NOISE_RE = re.compile(r"(Copyright\s+Afrobarometer\b|Page\s+\d+\b)", re.I)

# R2+ style
QUESTION_NUMBER_RE = re.compile(r"^\s*Question\s+Number\s*:\s*(.+?)\s*$", re.I)
QUESTION_RE = re.compile(r"^\s*Question\s*:\s*(.*)\s*$", re.I)
VARIABLE_LABEL_RE = re.compile(r"^\s*Variable\s+Label\s*:\s*(.*)\s*$", re.I)

# R1 style. Include the common typo "Varibale name" observed in older codebooks.
VARIABLE_NAME_RE = re.compile(r"^\s*(?:Variable|Varibale)\s+name\s*:\s*(.+?)\s*$", re.I)
QUESTION_TEXT_RE = re.compile(r"^\s*Question\s+text\s*[\-–—]\s*(.*?)\s*$", re.I)

# Shared field starts. Used to stop multiline capture.
FIELD_START_RE = re.compile(
    r"^\s*(Question\s+Number:|Question:|Variable\s+Label:|Variable\s+name:|Varibale\s+name:|"
    r"Question\s+text\s*[\-–—]|Values:|Value\s+Labels:|Source:|Note:|Notes:)\s*",
    re.I,
)

STOP_CAPTURE_RE = re.compile(r"^\s*(Values:|Value\s+Labels:|Source:|Note:|Notes:)\s*", re.I)


def normalize_space(s: object) -> str:
    if s is None:
        return ""
    s = str(s).replace("\u00a0", " ")
    s = s.replace("\ufffe", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_pdf_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = line.replace("\ufffe", "")
    line = NOISE_RE.sub(" ", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def norm_key(s: object) -> str:
    """Robust cross-source matching key; not necessarily the output variable."""
    s = normalize_space(s).upper()
    s = s.replace("-", "_").replace("/", "_").replace(".", "_")
    s = re.sub(r"[^A-Z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def normalize_text_for_dedup(s: str) -> str:
    s = normalize_space(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def first_nonempty(items: Iterable[str]) -> str:
    for x in items:
        x = normalize_space(x)
        if x:
            return x
    return ""


def unique_preserve_order(items: Iterable[str], dedup_normalized: bool = True) -> List[str]:
    out = []
    seen = set()
    for item in items:
        item = normalize_space(item)
        if not item:
            continue
        key = normalize_text_for_dedup(item) if dedup_normalized else item
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# -----------------------------
# Data/qnet variable metadata
# -----------------------------

ENCODINGS_TO_TRY = [None, "utf-8", "cp1252", "latin1", "iso-8859-1"]


def read_data_metadata(data_path: Optional[Path]) -> Tuple[List[str], Dict[str, str]]:
    if data_path is None:
        return [], {}

    suffix = data_path.suffix.lower()
    if suffix == ".csv":
        df0 = pd.read_csv(data_path, nrows=0)
        return list(df0.columns), {}

    if suffix not in {".sav", ".dta"}:
        raise ValueError(f"Unsupported data file type: {data_path.suffix}; use .sav, .dta, or .csv")

    if pyreadstat is None:
        raise RuntimeError("pyreadstat is required to read .sav/.dta metadata")

    reader = pyreadstat.read_sav if suffix == ".sav" else pyreadstat.read_dta
    last_err = None
    for enc in ENCODINGS_TO_TRY:
        try:
            _, meta = reader(str(data_path), metadataonly=True, encoding=enc)
            vars_ = list(meta.column_names)
            labels = {}
            for v, lab in zip(meta.column_names, meta.column_labels):
                lab = normalize_space(lab)
                if lab:
                    labels[str(v)] = lab
            return vars_, labels
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not read metadata from {data_path}: {last_err}")


def read_qnet_features(qnet_path: Optional[Path]) -> List[str]:
    if qnet_path is None:
        return []
    try:
        from quasinet.qnet import load_qnet
    except Exception as e:
        raise RuntimeError("quasinet is required for --qnet feature alignment") from e
    model = load_qnet(str(qnet_path))
    return [str(x) for x in model.feature_names]


# -----------------------------
# PDF parsing
# -----------------------------

def parse_codebook_pdf(pdf_path: Path) -> pd.DataFrame:
    """Parse both R1 Variable-name style and R2+ Question-Number style codebooks."""
    rows: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    active_field: Optional[str] = None
    active_question_label: Optional[str] = None

    def flush_current():
        nonlocal current, active_field, active_question_label
        if not current:
            return

        variable_raw = normalize_space(current.get("variable_raw"))
        if not variable_raw:
            current = None
            active_field = None
            active_question_label = None
            return

        variable_label = normalize_space(current.get("variable_label"))
        question_texts = current.get("question_texts") or []
        if not isinstance(question_texts, list):
            question_texts = []

        # Store one row per source text. The build stage will combine these.
        emitted = False
        for qt in question_texts:
            qt_text = normalize_space(qt.get("text", "")) if isinstance(qt, dict) else normalize_space(qt)
            qt_label = normalize_space(qt.get("label", "")) if isinstance(qt, dict) else ""
            if qt_text:
                rows.append({
                    "variable_pdf": variable_raw,
                    "variable_norm": norm_key(variable_raw),
                    "question_text": qt_text,
                    "text_label": qt_label,
                    "variable_label": variable_label,
                    "source": "codebook_question",
                    "codebook_page": current.get("page"),
                    "codebook_pdf": str(pdf_path),
                })
                emitted = True

        if variable_label:
            rows.append({
                "variable_pdf": variable_raw,
                "variable_norm": norm_key(variable_raw),
                "question_text": variable_label,
                "text_label": "variable_label",
                "variable_label": variable_label,
                "source": "codebook_variable_label",
                "codebook_page": current.get("page"),
                "codebook_pdf": str(pdf_path),
            })
            emitted = True

        if not emitted:
            rows.append({
                "variable_pdf": variable_raw,
                "variable_norm": norm_key(variable_raw),
                "question_text": "",
                "text_label": "",
                "variable_label": "",
                "source": "codebook_empty",
                "codebook_page": current.get("page"),
                "codebook_pdf": str(pdf_path),
            })

        current = None
        active_field = None
        active_question_label = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for pi, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = clean_pdf_line(raw_line)
                if not line:
                    continue

                # New block: R2+ style.
                m = QUESTION_NUMBER_RE.match(line)
                if m:
                    flush_current()
                    current = {
                        "variable_raw": normalize_space(m.group(1)),
                        "variable_label": "",
                        "question_texts": [],
                        "page": pi,
                    }
                    active_field = None
                    active_question_label = None
                    continue

                # New block: R1 style.
                m = VARIABLE_NAME_RE.match(line)
                if m:
                    flush_current()
                    current = {
                        "variable_raw": normalize_space(m.group(1)),
                        "variable_label": "",
                        "question_texts": [],
                        "page": pi,
                    }
                    active_field = None
                    active_question_label = None
                    continue

                if current is None:
                    continue

                # R2+ primary question field.
                m = QUESTION_RE.match(line)
                if m:
                    q = normalize_space(m.group(1))
                    current.setdefault("question_texts", []).append({"label": "Question", "text": q})
                    active_field = "question_text"
                    active_question_label = "Question"
                    continue

                # R1 country-/group-specific question field.
                m = QUESTION_TEXT_RE.match(line)
                if m:
                    label = normalize_space(m.group(1)) or "Question text"
                    current.setdefault("question_texts", []).append({"label": label, "text": ""})
                    active_field = "question_text"
                    active_question_label = label
                    continue

                # Variable label.
                m = VARIABLE_LABEL_RE.match(line)
                if m:
                    current["variable_label"] = normalize_space(m.group(1))
                    active_field = "variable_label"
                    active_question_label = None
                    continue

                # Stop question/label capture at metadata fields.
                if STOP_CAPTURE_RE.match(line):
                    active_field = None
                    active_question_label = None
                    continue

                # Multiline continuation.
                if active_field == "question_text":
                    qts = current.setdefault("question_texts", [])
                    if qts:
                        qts[-1]["text"] = normalize_space(str(qts[-1].get("text", "")) + " " + line)
                    continue

                if active_field == "variable_label":
                    # Variable labels are usually single-line; allow continuation only when line does not start a field.
                    if not FIELD_START_RE.match(line):
                        current["variable_label"] = normalize_space(str(current.get("variable_label", "")) + " " + line)
                    continue

    flush_current()

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=[
            "variable_pdf", "variable_norm", "question_text", "text_label", "variable_label",
            "source", "codebook_page", "codebook_pdf"
        ])
    return out.drop_duplicates().reset_index(drop=True)


# -----------------------------
# Build DTAG map
# -----------------------------

def combine_texts(question_texts: List[str], label: str = "", mode: str = "combined") -> str:
    question_texts = unique_preserve_order(question_texts, dedup_normalized=True)
    label = normalize_space(label)

    if mode == "best":
        # Prefer the longest actual question text over a terse variable label.
        actual_questions = [x for x in question_texts if normalize_text_for_dedup(x) != normalize_text_for_dedup(label)]
        if actual_questions:
            best = max(actual_questions, key=len)
        else:
            best = first_nonempty([label] + question_texts)
        return normalize_space(best)

    # combined: label first, then all non-duplicate question texts.
    pieces = []
    if label:
        pieces.append(label)
    pieces.extend(question_texts)
    pieces = unique_preserve_order(pieces, dedup_normalized=True)
    return normalize_space(" | ".join(pieces))


def build_dtag_map(
    pdf_rows: pd.DataFrame,
    data_vars: List[str],
    data_labels: Dict[str, str],
    qnet_features: List[str],
    text_mode: str = "combined",
    include_unmatched_pdf_vars: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dtag_map, audit)."""

    pdf_by_norm: Dict[str, List[dict]] = defaultdict(list)
    for _, r in pdf_rows.iterrows():
        pdf_by_norm[str(r.get("variable_norm", ""))].append(dict(r))

    data_exact_by_norm: Dict[str, str] = OrderedDict()
    for v in data_vars:
        data_exact_by_norm.setdefault(norm_key(v), str(v))

    qnet_exact_by_norm: Dict[str, str] = OrderedDict()
    for v in qnet_features:
        qnet_exact_by_norm.setdefault(norm_key(v), str(v))

    # Determine output variables and exact variable spellings.
    output_vars: List[Tuple[str, str]] = []  # (norm, exact output variable)

    if qnet_features:
        for v in qnet_features:
            nk = norm_key(v)
            if nk in pdf_by_norm or nk in data_exact_by_norm:
                output_vars.append((nk, str(v)))
    elif data_vars:
        for v in data_vars:
            output_vars.append((norm_key(v), str(v)))
    else:
        for nk, rows in pdf_by_norm.items():
            exact = normalize_space(rows[0].get("variable_pdf", nk))
            output_vars.append((nk, exact))

    if include_unmatched_pdf_vars:
        existing = {nk for nk, _ in output_vars}
        for nk, rows in pdf_by_norm.items():
            if nk not in existing:
                exact = normalize_space(rows[0].get("variable_pdf", nk))
                output_vars.append((nk, exact))

    map_rows = []
    audit_rows = []

    for nk, exact_var in output_vars:
        rows = pdf_by_norm.get(nk, [])
        codebook_questions = [normalize_space(r.get("question_text", "")) for r in rows if r.get("source") == "codebook_question"]
        codebook_labels = [normalize_space(r.get("variable_label", "")) for r in rows]
        codebook_var_label = first_nonempty(codebook_labels)

        # Data label fallback. Prefer exact var; then any data var with same norm.
        data_label = data_labels.get(exact_var, "")
        if not data_label and nk in data_exact_by_norm:
            data_label = data_labels.get(data_exact_by_norm[nk], "")

        label = first_nonempty([codebook_var_label, data_label])
        question_text = combine_texts(codebook_questions, label=label, mode=text_mode)

        # Final fallback: at least give a readable variable-derived label.
        if not question_text:
            question_text = label or exact_var.replace("_", " ")

        map_rows.append({
            "variable": exact_var,
            "question_text": question_text,
        })

        audit_rows.append({
            "variable": exact_var,
            "variable_norm": nk,
            "question_text": question_text,
            "codebook_variable_label": codebook_var_label,
            "data_variable_label": data_label,
            "n_codebook_question_texts": len(unique_preserve_order(codebook_questions)),
            "source_codebook_pages": "|".join(str(r.get("codebook_page")) for r in rows if r.get("codebook_page") is not None),
            "source_codebook_pdfs": "|".join(unique_preserve_order(str(r.get("codebook_pdf", "")) for r in rows)),
            "raw_codebook_texts_json": json.dumps(unique_preserve_order(codebook_questions), ensure_ascii=False),
        })

    dtag = pd.DataFrame(map_rows).drop_duplicates(subset=["variable"], keep="first")
    audit = pd.DataFrame(audit_rows).drop_duplicates(subset=["variable"], keep="first")

    return dtag, audit


# -----------------------------
# CLI
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build a DTAG-ready Afrobarometer variable -> question_text map")
    ap.add_argument("--data", type=Path, default=None, help="Optional .sav, .dta, or .csv survey data file for exact variables/labels")
    ap.add_argument("--codebook_pdf", type=Path, nargs="+", required=True, help="One or more Afrobarometer codebook PDFs")
    ap.add_argument("--qnet", type=Path, default=None, help="Optional qnet model; restrict output to exact qnet feature names")
    ap.add_argument("--out", type=Path, required=True, help="Output DTAG map CSV with variable,question_text")
    ap.add_argument("--audit_out", type=Path, default=None, help="Optional audit CSV; default: <out_stem>_audit.csv")
    ap.add_argument("--text-mode", choices=["combined", "best"], default="combined", help="combined keeps label + all wording; best keeps one best wording")
    ap.add_argument("--include-unmatched-pdf-vars", action="store_true", help="Include codebook variables not present in data/qnet")
    args = ap.parse_args()

    data_vars, data_labels = read_data_metadata(args.data)
    qnet_features = read_qnet_features(args.qnet)

    pdf_frames = [parse_codebook_pdf(p) for p in args.codebook_pdf]
    pdf_rows = pd.concat(pdf_frames, ignore_index=True) if pdf_frames else pd.DataFrame()

    dtag, audit = build_dtag_map(
        pdf_rows=pdf_rows,
        data_vars=data_vars,
        data_labels=data_labels,
        qnet_features=qnet_features,
        text_mode=args.text_mode,
        include_unmatched_pdf_vars=args.include_unmatched_pdf_vars,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    dtag.to_csv(args.out, index=False)

    audit_out = args.audit_out or args.out.with_name(args.out.stem + "_audit.csv")
    audit_out.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(audit_out, index=False)

    print(f"Wrote DTAG map : {args.out}")
    print(f"Wrote audit    : {audit_out}")
    print(f"Rows/variables : {len(dtag)}")
    print(f"With PDF text  : {(audit['n_codebook_question_texts'].fillna(0).astype(int) > 0).sum() if not audit.empty else 0}")
    if args.data:
        print(f"Data variables : {len(data_vars)}")
    if args.qnet:
        print(f"Qnet features  : {len(qnet_features)}")


if __name__ == "__main__":
    main()
