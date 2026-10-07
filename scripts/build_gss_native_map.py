#!/usr/bin/env python3
"""Build a DTAG semantic map aligned to a native GSS LSM model.

Supported GSS documentation formats
-----------------------------------

1. Older cumulative NORC codebooks, e.g. 1972-2018:

       NATFARE    WELFARE
       POLVIEWS   THINK OF SELF AS LIBERAL OR CONSERVATIVE

   and detailed blocks such as:

       K. Welfare

       [VAR: NATFARE]

2. Newer single-year GSS codebooks, e.g. 2021:

       Variable: CLMTCAUS        Type: Numeric
       Label: There has been a lot of discussion about the world's climate...
       Which of the following statements comes closest to your opinion?
       Notes: ...

   Labels may begin on the line after ``Label:`` and may span multiple lines.

Semantic source precedence
--------------------------

Modern single-year codebooks:
    Variable:/Label: detailed record

Older cumulative codebooks:
    fixed-width variable index
        >
    [VAR: ...] nearby heading

The index is preferred over the old detailed-block heading because the latter
may contain questionnaire/navigation text such as "CARD A8", whereas the
index often has the cleaner semantic descriptor.

The native LSM feature list is authoritative. Every native feature is retained
in the output map, so model/map overlap remains 100% by construction.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_backend import load_model  # noqa: E402


# ---------------------------------------------------------------------------
# Newer single-year GSS codebooks
# ---------------------------------------------------------------------------

MODERN_VAR_RE = re.compile(
    r"^\s*Variable:\s*([A-Za-z0-9_]+)\b.*$",
    re.I,
)

MODERN_LABEL_RE = re.compile(
    r"^\s*Label:\s*(.*)\s*$",
    re.I,
)

MODERN_STOP_RE = re.compile(
    r"^\s*(?:"
    r"Notes?:|"
    r"LABEL(?:\s+VALUE)?\b|"
    r"RESERVED\s+CODES:|"
    r"TOTALS:|"
    r"SUBTOTALS:|"
    r"Variable:"
    r")",
    re.I,
)


# ---------------------------------------------------------------------------
# Older cumulative GSS codebooks
# ---------------------------------------------------------------------------

OLD_VAR_BLOCK_RE = re.compile(
    r"^\s*\[\s*VAR\s*:\s*([A-Za-z0-9_]+)\s*\]\s*$",
    re.I,
)

# Require 2+ spaces to reduce accidental matching of modern section indexes.
OLD_INDEX_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]{1,39})\s{2,}(.+?)\s*$"
)


# ---------------------------------------------------------------------------
# Shared patterns
# ---------------------------------------------------------------------------

PAGE_RE = re.compile(
    r"^\s*Page\s+\d+\b",
    re.I,
)

SECTION_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"[A-Z]\.|"
    r"[IVXLCDM]+\.|"
    r"\d+\."
    r")\s+",
    re.I,
)

OLD_BAD_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"RESPONSE|"
    r"PUNCH|"
    r"YEAR|"
    r"LABEL|"
    r"RESERVED|"
    r"TOTALS|"
    r"SUBTOTALS|"
    r"GENERAL SOCIAL SURVEYS|"
    r"NORC"
    r")\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def norm(value: str) -> str:
    """Collapse whitespace and remove PDF non-breaking spaces."""
    return re.sub(
        r"\s+",
        " ",
        str(value or "").replace("\u00a0", " "),
    ).strip()


def semantic_norm(value: str) -> str:
    """Normalize strings for detecting variable-name-only labels."""
    s = norm(value).lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def usable_label(variable: str, label: str) -> bool:
    """Return True only when label appears to carry semantic information."""
    variable = norm(variable)
    label = norm(label)

    if not variable or not label:
        return False

    if semantic_norm(variable) == semantic_norm(label):
        return False

    # Reject cross-reference material such as:
    #     (No SCIBNFTSNV)
    if re.fullmatch(
        r"\(?\s*No\s+[A-Za-z0-9_]+\s*\)?",
        label,
        re.I,
    ):
        return False

    return True


# ---------------------------------------------------------------------------
# Modern parser
# ---------------------------------------------------------------------------

def parse_modern_blocks(
    lines: List[str],
    page_num: int,
) -> Dict[str, Tuple[str, int, str]]:
    """Parse Variable:/Label: records from modern single-year codebooks."""

    result: Dict[str, Tuple[str, int, str]] = {}

    i = 0

    while i < len(lines):
        m = MODERN_VAR_RE.match(lines[i])

        if not m:
            i += 1
            continue

        variable = norm(m.group(1)).lower()

        label_lines: List[str] = []
        saw_label = False

        j = i + 1

        while j < len(lines):

            if MODERN_VAR_RE.match(lines[j]):
                break

            lm = MODERN_LABEL_RE.match(lines[j])

            if lm:
                saw_label = True

                first = norm(lm.group(1))

                if first:
                    label_lines.append(first)

                j += 1

                while j < len(lines):
                    raw = lines[j]

                    if MODERN_VAR_RE.match(raw):
                        break

                    if MODERN_STOP_RE.match(raw):
                        break

                    value = norm(raw)

                    if value:
                        label_lines.append(value)

                    j += 1

                break

            j += 1

        label = norm(" ".join(label_lines))

        if saw_label and usable_label(variable, label):
            result[variable] = (
                label,
                page_num,
                "GSS_MODERN_CODEBOOK",
            )

        i = max(i + 1, j)

    return result


# ---------------------------------------------------------------------------
# Older cumulative-codebook parser
# ---------------------------------------------------------------------------

def parse_old_var_blocks(
    lines: List[str],
    page_num: int,
) -> Dict[str, Tuple[str, int, str]]:
    """Parse [VAR: NAME] records and nearby human-readable headings."""

    result: Dict[str, Tuple[str, int, str]] = {}

    for i, raw in enumerate(lines):
        m = OLD_VAR_BLOCK_RE.match(raw)

        if not m:
            continue

        variable = norm(m.group(1)).lower()
        heading = ""

        for j in range(i - 1, max(-1, i - 12), -1):
            candidate = norm(lines[j])

            if not candidate:
                continue

            if PAGE_RE.match(candidate):
                continue

            if OLD_VAR_BLOCK_RE.match(candidate):
                continue

            candidate = SECTION_PREFIX_RE.sub("", candidate)
            candidate = norm(candidate)

            if not candidate:
                continue

            if OLD_BAD_HEADING_RE.match(candidate):
                continue

            if re.match(r"^[0-9]", candidate):
                continue

            if sum(ch.isdigit() for ch in candidate) > 8:
                continue

            if usable_label(variable, candidate):
                heading = candidate
                break

        if heading:
            result.setdefault(
                variable,
                (
                    heading,
                    page_num,
                    "GSS_VAR_BLOCK",
                ),
            )

    return result


def parse_old_index(
    lines: List[str],
    page_num: int,
) -> Dict[str, Tuple[str, int, str]]:
    """Parse the fixed-width variable index in older cumulative codebooks."""

    result: Dict[str, Tuple[str, int, str]] = {}

    for raw in lines:
        m = OLD_INDEX_RE.match(raw)

        if not m:
            continue

        variable = norm(m.group(1)).lower()
        label = norm(m.group(2))

        # Modern section index:
        #
        # IMMLIMIT          4.212 America should limit immigration...
        #
        # Do not treat this as the old cumulative index.
        if re.match(r"^\d+\.\d+\b", label):
            continue

        if not usable_label(variable, label):
            continue

        result.setdefault(
            variable,
            (
                label,
                page_num,
                "GSS_INDEX",
            ),
        )

    return result


# ---------------------------------------------------------------------------
# Unified parser
# ---------------------------------------------------------------------------

def parse_codebook(path: Path) -> pd.DataFrame:
    """Parse cumulative or modern GSS codebook PDFs.

    Precedence:

        modern Variable:/Label:
            >
        old cumulative fixed-width index
            >
        old [VAR: ...] nearby heading

    The old index is intentionally preferred over the old detailed-block
    heading because the latter can contain navigational labels such as
    "CARD A8".
    """

    modern: Dict[str, Tuple[str, int, str]] = {}
    old_blocks: Dict[str, Tuple[str, int, str]] = {}
    old_index: Dict[str, Tuple[str, int, str]] = {}

    with pdfplumber.open(str(path)) as pdf:

        for page_num, page in enumerate(pdf.pages, start=1):

            try:
                text = page.extract_text(layout=True) or ""
            except Exception:
                text = page.extract_text() or ""

            lines = text.splitlines()

            for variable, rec in parse_modern_blocks(
                lines,
                page_num,
            ).items():
                modern[variable] = rec

            for variable, rec in parse_old_var_blocks(
                lines,
                page_num,
            ).items():
                old_blocks.setdefault(variable, rec)

            for variable, rec in parse_old_index(
                lines,
                page_num,
            ).items():
                old_index.setdefault(variable, rec)

    all_variables = sorted(
        set(modern)
        | set(old_index)
        | set(old_blocks)
    )

    rows: List[dict] = []

    for variable in all_variables:

        if variable in modern:
            text, page, source = modern[variable]

        elif variable in old_index:
            text, page, source = old_index[variable]

        else:
            text, page, source = old_blocks[variable]

        if not usable_label(variable, text):
            continue

        rows.append(
            {
                "variable_key": variable,
                "question_text": norm(text),
                "codebook_page": page,
                "codebook_source": source,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "variable_key",
            "question_text",
            "codebook_page",
            "codebook_source",
        ],
    )


# ---------------------------------------------------------------------------
# Map builder
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Build a native-model-aligned GSS semantic map "
            "from an official GSS codebook."
        )
    )

    ap.add_argument(
        "--model",
        required=True,
        help="native GSS LSM model directory",
    )

    ap.add_argument(
        "--codebook",
        required=True,
        help="GSS codebook PDF",
    )

    ap.add_argument(
        "--out",
        required=True,
        help="output semantic-map CSV",
    )

    ap.add_argument(
        "--min-text-coverage",
        type=float,
        default=0.0,
        help=(
            "exit nonzero when semantic text coverage "
            "is below this fraction"
        ),
    )

    args = ap.parse_args()

    def resolve(value: str) -> Path:
        p = Path(value).expanduser()

        if p.is_absolute():
            return p.resolve()

        return (ROOT / p).resolve()

    model_path = resolve(args.model)
    codebook_path = resolve(args.codebook)
    out_path = resolve(args.out)

    if not model_path.is_dir():
        raise SystemExit(
            f"Model directory not found: {model_path}"
        )

    if not codebook_path.is_file():
        raise SystemExit(
            f"Codebook not found: {codebook_path}"
        )

    model = load_model(
        model_path,
        backend="native_lsm",
        preload=False,
    )

    features = [str(v) for v in model.feature_names]

    docs = parse_codebook(codebook_path)

    lookup = {
        str(row.variable_key).lower(): (
            str(row.question_text or ""),
            row.codebook_page,
            str(row.codebook_source or ""),
        )
        for row in docs.itertuples(index=False)
    }

    rows: List[dict] = []
    matched = 0

    for variable in features:
        text, page, source = lookup.get(
            variable.lower(),
            ("", "", ""),
        )

        text = norm(text)

        if usable_label(variable, text):
            matched += 1
            provenance = source or "GSS_CODEBOOK"
        else:
            text = variable
            provenance = "NATIVE_NAME"
            page = ""

        rows.append(
            {
                "variable": variable,
                "question_text": text,
                "question_text_filled": text,
                "source": provenance,
                "source_year": "",
                "codebook_page": page,
                "map_provenance": provenance,
            }
        )

    out_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    pd.DataFrame(rows).to_csv(
        out_path,
        index=False,
    )

    coverage = matched / max(1, len(features))

    print(f"Wrote: {out_path}")
    print(f"Model variables: {len(features)}")
    print(f"Parsed codebook variables: {len(docs)}")

    print(
        f"Codebook semantic matches: "
        f"{matched}/{len(features)} = {coverage:.3f}"
    )

    print("Model-map overlap: 1.000 by construction")

    if not docs.empty:
        print("\nCODEBOOK SOURCE COUNTS")

        print(
            docs["codebook_source"]
            .value_counts()
            .to_string()
        )

    if coverage < args.min_text_coverage:
        raise SystemExit(
            f"Semantic text coverage {coverage:.3f} "
            f"< required {args.min_text_coverage:.3f}"
        )


if __name__ == "__main__":
    main()
