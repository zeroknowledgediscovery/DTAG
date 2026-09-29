#!/usr/bin/env python3
"""Build DTAG semantic maps for native-LSM Eurobarometer models.

Primary input:
  - native LSM source_maps/ for the exact model feature names
  - GESIS Variable Report PDF (ZAxxxx_cdb.pdf) for variable labels/question text

Output:
  maps/eurobarometer/ZAxxxx_map.csv

The parser is intentionally conservative. It only assigns codebook question text
when a variable block can be matched to an actual native-LSM feature name.
Unmatched model features are retained with a fallback semantic text based on
their variable label/name so model-map overlap remains complete and auditable.

Examples:
  python3 scripts/build_eurobarometer_maps.py --za ZA7575

  python3 scripts/build_eurobarometer_maps.py --all

  python3 scripts/build_eurobarometer_maps.py \
      --za ZA7575 \
      --codebook data/eurobarometer/codebooks/ZA7575_cdb.pdf \
      --model "$DTAG_MODEL_ROOT/eurobarometer/ZA7575" \
      --out maps/eurobarometer/ZA7575_map.csv
"""
from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dtag_paths import model_path  # noqa: E402
DEFAULT_CODEBOOK_DIR = ROOT / "data" / "eurobarometer" / "codebooks"
DEFAULT_MODEL_DIR = model_path("eurobarometer")
DEFAULT_OUT_DIR = ROOT / "maps" / "eurobarometer"

sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402


QUESTION_CODE_RE = re.compile(r"^[A-Z]{1,6}(?:[._-]?\d+)+(?:[A-Z0-9_.\-]*)?$", re.I)
ANSWER_LINE_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s+\S")
PAGE_NO_RE = re.compile(r"^\s*page\s+\d+\s*$", re.I)
GESIS_HEADER_RE = re.compile(r"^GESIS\s+Study\s+No\.", re.I)
COMPARABILITY_RE = re.compile(
    r"^(Comparability|Filter|Notes?|Archive remarks?|Questionnaire|Universe|"
    r"Country-specific|Values? and labels?)\s*:",
    re.I,
)


@dataclass
class VariableDoc:
    variable: str
    variable_label: str
    question_number: str
    question_text: str
    page: int


def normalize_za(value: str) -> str:
    s = str(value).strip().upper()
    if s.startswith("ZA"):
        s = s[2:]
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"Invalid ZA id: {value!r}")
    return "ZA" + s.zfill(4)


def resolve_model_dir(base: Path, za: str) -> Path:
    direct = base / za
    if direct.is_dir():
        return direct.resolve()
    hits = sorted(
        p for p in base.iterdir()
        if p.is_dir() and p.name.upper().startswith(za)
    ) if base.is_dir() else []
    if len(hits) == 1:
        return hits[0].resolve()
    if not hits:
        raise FileNotFoundError(f"No native Eurobarometer model found for {za} under {base}")
    raise RuntimeError(
        f"Multiple model directories match {za}:\n  "
        + "\n  ".join(str(p) for p in hits)
    )


def _clean_line(line: str) -> str:
    s = str(line or "").replace("\u00ad", "").replace("\x00", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _join_text(lines: Sequence[str]) -> str:
    out: List[str] = []
    for raw in lines:
        s = _clean_line(raw)
        if not s:
            continue
        if out and out[-1].endswith("-") and s and s[0].islower():
            out[-1] = out[-1][:-1] + s
        else:
            out.append(s)
    return " ".join(out).strip()


def _feature_lookup(features: Sequence[str]) -> Tuple[Dict[str, str], List[str]]:
    exact_lower = {str(v).lower(): str(v) for v in features}
    ordered = sorted((str(v) for v in features), key=len, reverse=True)
    return exact_lower, ordered


def _match_header(line: str, exact_lower: Dict[str, str], ordered: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Match both modern and older GESIS variable-block headers.

    Modern reports commonly use:
        q1_6 - NATIONALITY: FRANCE

    Older GESIS Variable Reports use a fixed-width form:
        v12            Q2 LIFE SATISFACTION

    The older reports later repeat the variable name inside indented frequency
    and crosstab tables.  Requiring the fixed-width header to begin near the
    left margin prevents those table rows from being mistaken for new blocks.
    """
    raw = str(line or "").replace("\u00ad", "").replace("\x00", " ")
    s = _clean_line(raw)

    # Modern "variable - label" form.
    if " - " in s:
        left, right = s.split(" - ", 1)
        key = left.strip().lower()
        if key in exact_lower:
            return exact_lower[key], right.strip()

        # Some PDFs merge punctuation/spacing oddly. Use a conservative
        # case-insensitive startswith only when followed by a separator.
        low = s.lower()
        for feature in ordered:
            fl = feature.lower()
            if low.startswith(fl):
                rem = s[len(feature):].lstrip()
                if rem.startswith("-"):
                    return feature, rem[1:].strip()

    # Older Variable Report form. In layout-preserving extraction these look
    # fixed-width, e.g. "v12            Q2 LIFE SATISFACTION". pdfplumber may
    # collapse that spacing to a single space, so do not require multiple
    # spaces. A true block header starts with the exact model variable token
    # and has a nonempty label after it. Crosstab/table repetitions either do
    # not start with the variable ("isocntry by v12 ...") or contain only the
    # bare variable name, so they are not matched here.
    m = re.match(r"^\s*(\S+)\s+(.+?)\s*$", raw)
    if m:
        key = m.group(1).strip().lower()
        label = _clean_line(m.group(2))
        if key in exact_lower and label:
            return exact_lower[key], label

    return None


def _extract_question(block_lines: Sequence[str], variable: str) -> Tuple[str, str]:
    lines = [_clean_line(x) for x in block_lines if _clean_line(x)]
    if not lines:
        return "", ""

    qnum = ""
    start = 0

    # GESIS variable reports normally place QUESTION NUMBER immediately after
    # the variable header. Find a short question-code line near the block top.
    for i, line in enumerate(lines[:12]):
        compact = line.replace(" ", "")
        if (
            len(compact) <= 24
            and QUESTION_CODE_RE.fullmatch(compact)
        ):
            qnum = line
            start = i + 1
            break

    if not qnum:
        return "", ""

    text_lines: List[str] = []
    var_low = variable.lower()
    qnum_low = qnum.lower()

    for line in lines[start:]:
        low = line.lower()

        if PAGE_NO_RE.match(line) or GESIS_HEADER_RE.match(line):
            continue
        if COMPARABILITY_RE.match(line):
            break
        if low.startswith("last trend:") or low.startswith("trend:"):
            break

        # Item/coding line such as "Q1_6 France" marks the transition from
        # full question/instructions to answer-category documentation.
        first = line.split(" ", 1)[0].strip()
        first_low = first.lower()
        if (
            text_lines
            and (
                first_low == var_low
                or (
                    first_low.startswith(qnum_low)
                    and first_low != qnum_low
                )
            )
        ):
            break

        # Once question text has started, numeric code-value lines denote the
        # answer table rather than question wording.
        if text_lines and ANSWER_LINE_RE.match(line):
            break

        # Avoid swallowing frequency-table boilerplate.
        if text_lines and (
            low.startswith("country ")
            or low == "total"
            or low.startswith("weighted")
            or low.startswith("unweighted")
            or low.startswith("valid percent")
        ):
            break

        text_lines.append(line)

        # Very long instruction blocks are possible, but semantic mapping does
        # not benefit from accidentally consuming pages of tabular material.
        if sum(len(x) for x in text_lines) > 5000:
            break

    return qnum, _join_text(text_lines)



TREND_VAR_RE = re.compile(
    r"^(.*?)\\s*VARIABLE\\s+NAME:\\s*([A-Za-z0-9_]+)\\s*$",
    re.I,
)

TREND_VARIABLE_ALIASES = {
    # ZA4669 codebook/model naming mismatches.
    "info_sport": "info_sports",
    "heriditary_disease": "hereditary_disease",
}


def _extract_trend_question(block_lines: Sequence[str]) -> Tuple[str, str]:
    """Extract semantic prose from ZA4669-style harmonized trend-file blocks."""
    lines = [_clean_line(x) for x in block_lines if _clean_line(x)]
    if not lines:
        return "", ""

    stop_prefixes = (
        "options",
        "codes",
        "output",
        "frequency distribution",
        "sample (n)",
        "total ",
    )

    qnum = ""
    text_lines: List[str] = []
    saw_q = False

    for line in lines:
        low = line.lower()

        if any(low.startswith(p) for p in stop_prefixes):
            break
        if re.fullmatch(r"\\d+", line):
            continue
        if re.match(r"^\\d+(?:\\.\\d+)+\\.?\\s+", line):
            continue

        # ZA4669 generally marks substantive wording with a simple "Q.".
        if low == "q." or low.startswith("q. "):
            saw_q = True
            qnum = "Q."
            rest = line[2:].strip()
            if rest:
                text_lines.append(rest)
            continue

        # If this is a survey-question block, ignore descriptive material before
        # Q. and keep only question wording thereafter.
        if saw_q:
            text_lines.append(line)

    if saw_q:
        return qnum, _join_text(text_lines)

    # Technical/demographic blocks often have no Q. marker. Preserve their
    # leading descriptive prose until coding/frequency material begins.
    prose: List[str] = []
    for line in lines:
        low = line.lower()
        if any(low.startswith(p) for p in stop_prefixes):
            break
        if re.fullmatch(r"\\d+", line):
            continue
        if re.match(r"^\\d+(?:\\.\\d+)+\\.?\\s+", line):
            continue
        prose.append(line)
        if sum(len(x) for x in prose) > 3000:
            break

    return "", _join_text(prose)


def parse_trend_file_report(
    pdf_path: Path,
    features: Sequence[str],
) -> Dict[str, VariableDoc]:
    """Parse harmonized Eurobarometer trend files such as ZA4669.

    These codebooks use headings like:
        News Interest - Sports    VARIABLE NAME: int_sport

    pdfplumber fragments many of these headings in ZA4669, while Poppler's
    pdftotext -layout preserves them reliably. Use pdftotext for this special
    fallback parser and retain page boundaries via form-feed characters.
    """
    exact_lower, _ = _feature_lookup(features)
    docs: Dict[str, VariableDoc] = {}

    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"pdftotext failed for {pdf_path}: {proc.stderr.strip()}"
        )

    current_var: Optional[str] = None
    current_label = ""
    current_page = -1
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_var, current_label, current_page, current_lines
        if current_var is None:
            return

        qnum, qtext = _extract_trend_question(current_lines)
        candidate = VariableDoc(
            variable=current_var,
            variable_label=current_label,
            question_number=qnum,
            question_text=qtext,
            page=current_page,
        )
        previous = docs.get(current_var)
        if previous is None:
            docs[current_var] = candidate
        else:
            old_score = len(previous.variable_label) + len(previous.question_text)
            new_score = len(candidate.variable_label) + len(candidate.question_text)
            if new_score > old_score:
                docs[current_var] = candidate

        current_var = None
        current_label = ""
        current_page = -1
        current_lines = []

    pages = proc.stdout.split("\f")
    for page_no, page_text in enumerate(pages, start=1):
        raw_lines = page_text.splitlines()

        # Some headings are broken across adjacent lines.  Construct a
        # normalized stream and also look one line ahead when VARIABLE NAME:
        # is separated from its label.
        i = 0
        while i < len(raw_lines):
            raw = raw_lines[i]
            line = _clean_line(raw)
            if not line:
                i += 1
                continue

            # Primary form: label and VARIABLE NAME occur on the same line.
            m = re.search(
                r"^(.*?)\s*VARIABLE\s+NAME:\s*([A-Za-z0-9_]+)\s*$",
                line,
                flags=re.I,
            )

            # Secondary form: the phrase and variable are split across two
            # adjacent extracted lines.
            if not m and "VARIABLE NAME:" in line.upper() and i + 1 < len(raw_lines):
                joined = _clean_line(line + " " + raw_lines[i + 1])
                m = re.search(
                    r"^(.*?)\s*VARIABLE\s+NAME:\s*([A-Za-z0-9_]+)\s*$",
                    joined,
                    flags=re.I,
                )
                if m:
                    i += 1

            if m:
                key = m.group(2).strip().lower()
                key = TREND_VARIABLE_ALIASES.get(key, key)
                if key in exact_lower:
                    flush()
                    current_var = exact_lower[key]
                    label = _clean_line(m.group(1))
                    current_label = label or current_var
                    current_page = page_no
                    current_lines = []
                    i += 1
                    continue

            if current_var is not None:
                current_lines.append(line)

            i += 1

    flush()
    return docs


def parse_variable_report(pdf_path: Path, features: Sequence[str]) -> Dict[str, VariableDoc]:
    exact_lower, ordered = _feature_lookup(features)
    docs: Dict[str, VariableDoc] = {}

    current_var: Optional[str] = None
    current_label = ""
    current_page = -1
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_var, current_label, current_page, current_lines
        if current_var is None:
            return
        qnum, qtext = _extract_question(current_lines, current_var)
        previous = docs.get(current_var)
        candidate = VariableDoc(
            variable=current_var,
            variable_label=current_label,
            question_number=qnum,
            question_text=qtext,
            page=current_page,
        )
        # Keep the richer duplicate if PDF extraction repeats a block/header.
        if previous is None:
            docs[current_var] = candidate
        else:
            old_score = len(previous.question_text) + len(previous.variable_label)
            new_score = len(candidate.question_text) + len(candidate.variable_label)
            if new_score > old_score:
                docs[current_var] = candidate
        current_var = None
        current_label = ""
        current_page = -1
        current_lines = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            if not text:
                continue
            for raw in text.splitlines():
                line = _clean_line(raw)
                if not line:
                    continue
                # Pass the original extracted line to header matching because
                # older GESIS reports encode block structure via indentation
                # and fixed-width spacing. Store normalized text only after
                # header detection.
                matched = _match_header(raw, exact_lower, ordered)
                if matched:
                    flush()
                    current_var, current_label = matched
                    current_page = page_no
                    current_lines = []
                    continue
                if current_var is not None:
                    current_lines.append(line)

    flush()
    return docs


def build_map(za: str, model_dir: Path, codebook: Path, out_path: Path) -> dict:
    model = load_model(model_dir, backend="native_lsm", preload=False)
    features = [str(v) for v in model.feature_names]
    docs = parse_variable_report(codebook, features)

    # Harmonized trend-file codebooks such as ZA4669 use a different explicit
    # "VARIABLE NAME:" syntax. The standard parser can occasionally find a few
    # accidental/spurious matches in such files, so do not require exactly zero
    # matches before trying the trend parser. If standard coverage is low, run
    # the trend parser and keep the richer per-variable result.
    if len(docs) < max(10, int(0.50 * len(features))):
        trend_docs = parse_trend_file_report(codebook, features)
        for var, candidate in trend_docs.items():
            previous = docs.get(var)
            if previous is None:
                docs[var] = candidate
            else:
                old_score = len(previous.variable_label) + len(previous.question_text)
                new_score = len(candidate.variable_label) + len(candidate.question_text)
                if new_score > old_score:
                    docs[var] = candidate

    rows = []
    n_question = 0
    n_label = 0
    for var in features:
        d = docs.get(var)
        label = d.variable_label.strip() if d else ""
        qnum = d.question_number.strip() if d else ""
        qtext = d.question_text.strip() if d else ""
        if qtext:
            n_question += 1
        if label:
            n_label += 1

        # For semantic selection, actual full question wording is preferred.
        # Variable label is a useful fallback; raw variable name is last resort.
        filled = qtext or label or var
        rows.append(
            {
                "variable": var,
                "question_number": qnum,
                "variable_label": label,
                "question_text": qtext,
                "question_text_filled": filled,
                "source": "GESIS Variable Report" if d else "native LSM source map",
                "source_page": d.page if d else "",
                "za_id": za,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_path, index=False)

    stats = {
        "za_id": za,
        "model": str(model_dir),
        "codebook": str(codebook),
        "out": str(out_path),
        "model_variables": len(features),
        "matched_variable_blocks": len(docs),
        "with_variable_label": n_label,
        "with_question_text": n_question,
        "block_coverage": len(docs) / max(1, len(features)),
        "question_text_coverage": n_question / max(1, len(features)),
    }
    return stats


def _build_map_worker(
    za: str,
    model_dir: str,
    codebook: str,
    out_path: str,
    queue,
) -> None:
    try:
        stats = build_map(
            za,
            Path(model_dir),
            Path(codebook),
            Path(out_path),
        )
        queue.put(("ok", stats))
    except Exception as e:
        queue.put(("error", f"{type(e).__name__}: {e}"))


def build_map_bounded(
    za: str,
    model_dir: Path,
    codebook: Path,
    out_path: Path,
    timeout_sec: float,
) -> dict:
    """Build one map without letting a pathological PDF stall the whole batch."""
    if timeout_sec <= 0:
        return build_map(za, model_dir, codebook, out_path)

    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    proc = ctx.Process(
        target=_build_map_worker,
        args=(za, str(model_dir), str(codebook), str(out_path), queue),
    )
    proc.start()
    proc.join(timeout_sec)

    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        raise TimeoutError(
            f"map extraction exceeded {timeout_sec:.0f}s for {za}; "
            "leave this wave on the legacy Eurobarometer map fallback"
        )

    if queue.empty():
        raise RuntimeError(
            f"map worker exited without a result for {za} "
            f"(exitcode={proc.exitcode})"
        )

    status, payload = queue.get()
    if status != "ok":
        raise RuntimeError(str(payload))
    return payload


def discover_codebooks(codebook_dir: Path) -> List[Tuple[str, Path]]:
    out = []
    for p in sorted(codebook_dir.glob("ZA*_cdb.pdf")):
        m = re.match(r"^(ZA\d+)_cdb\.pdf$", p.name, flags=re.I)
        if not m:
            continue
        out.append((normalize_za(m.group(1)), p.resolve()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--za", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--codebook", default="")
    ap.add_argument("--codebook-dir", default=str(DEFAULT_CODEBOOK_DIR))
    ap.add_argument("--model", default="")
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--out", default="")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--min-question-coverage", type=float, default=0.0)
    ap.add_argument(
        "--parse-timeout",
        type=float,
        default=120.0,
        help="max seconds per PDF/map build; <=0 disables timeout",
    )
    ap.add_argument("--inspect-variable", action="append", default=[],
                    help="print selected output rows after building; repeatable")
    args = ap.parse_args()

    codebook_dir = Path(args.codebook_dir).expanduser().resolve()
    model_base = Path(args.model_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    jobs: List[Tuple[str, Path, Path, Path]] = []

    if args.all:
        for za, codebook in discover_codebooks(codebook_dir):
            try:
                model_dir = resolve_model_dir(model_base, za)
            except Exception as e:
                print(f"SKIP {za}: {e}", file=sys.stderr)
                continue
            out_path = out_dir / f"{za}_map.csv"
            jobs.append((za, model_dir, codebook, out_path))
    else:
        if not args.za:
            raise SystemExit("Use --za ZAxxxx or --all")
        za = normalize_za(args.za)

        if args.model:
            model_dir = Path(args.model).expanduser()
            if not model_dir.is_absolute():
                model_dir = ROOT / model_dir
            model_dir = model_dir.resolve()
        else:
            model_dir = resolve_model_dir(model_base, za)

        if args.codebook:
            codebook = Path(args.codebook).expanduser()
            if not codebook.is_absolute():
                codebook = ROOT / codebook
            codebook = codebook.resolve()
        else:
            codebook = (codebook_dir / f"{za}_cdb.pdf").resolve()

        if not codebook.is_file():
            raise SystemExit(f"Codebook not found: {codebook}")

        if args.out:
            out_path = Path(args.out).expanduser()
            if not out_path.is_absolute():
                out_path = ROOT / out_path
            out_path = out_path.resolve()
        else:
            out_path = out_dir / f"{za}_map.csv"

        jobs.append((za, model_dir, codebook, out_path))

    if not jobs:
        raise SystemExit("No buildable Eurobarometer map jobs found.")

    failures = 0
    for za, model_dir, codebook, out_path in jobs:
        print(f"\n== {za} ==")
        print(f"model:    {model_dir}")
        print(f"codebook: {codebook}")
        print(f"out:      {out_path}")
        try:
            stats = build_map_bounded(
                za,
                model_dir,
                codebook,
                out_path,
                timeout_sec=args.parse_timeout,
            )
        except Exception as e:
            failures += 1
            print(f"FAIL: {e}", file=sys.stderr)
            continue

        print(f"model variables:         {stats['model_variables']}")
        print(f"matched variable blocks: {stats['matched_variable_blocks']} "
              f"({stats['block_coverage']:.3f})")
        print(f"with variable labels:    {stats['with_variable_label']}")
        print(f"with question text:      {stats['with_question_text']} "
              f"({stats['question_text_coverage']:.3f})")

        if args.inspect_variable:
            built = pd.read_csv(out_path, dtype=str, keep_default_na=False)
            for requested in args.inspect_variable:
                x = built[built["variable"].str.lower() == str(requested).lower()]
                print(f"\nINSPECT {requested}:")
                if x.empty:
                    print("  NOT FOUND IN MODEL/MAP")
                else:
                    cols = [
                        "variable", "question_number", "variable_label",
                        "question_text", "question_text_filled", "source_page"
                    ]
                    print(x[cols].to_string(index=False))

        if stats["question_text_coverage"] < args.min_question_coverage:
            failures += 1
            print(
                f"FAIL coverage {stats['question_text_coverage']:.3f} "
                f"< required {args.min_question_coverage:.3f}",
                file=sys.stderr,
            )
        else:
            print("PASS")

    if failures:
        raise SystemExit(f"{failures} Eurobarometer map job(s) failed.")


if __name__ == "__main__":
    main()
