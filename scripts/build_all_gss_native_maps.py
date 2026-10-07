#!/usr/bin/env python3
"""Build native GSS DTAG semantic maps for every installed GSS wave.

Semantic resolution order
-------------------------

For every native model feature:

1. Authoritative codebook for that wave:
      1972-2018 -> GSS_1972_2018_Codebook.pdf
      2021      -> GSS_2021_Codebook.pdf
      2022      -> GSS_2022_Codebook.pdf
      2024      -> GSS_2024_Codebook.pdf

2. Meaningful semantic text already present in the exact-year canonical map.

3. Exact-variable semantic text from the nearest other GSS wave map.

4. Native feature-name fallback.

Important properties
--------------------

- Native LSM feature names are authoritative.
- Every native feature appears exactly once in its output map.
- Existing maps are snapshotted before anything is overwritten.
- Native-name fallbacks are never reused as semantic donors.
- Codebooks are parsed only once per run.
- Provenance is recorded for every semantic assignment.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_gss_native_map import (  # noqa: E402
    norm,
    parse_codebook,
    usable_label,
)
from model_backend import load_model  # noqa: E402
from dtag_paths import model_path  # noqa: E402


# ---------------------------------------------------------------------------
# Codebooks
# ---------------------------------------------------------------------------

CODEBOOK_DIR = ROOT / "data" / "gss" / "codebooks"

CUMULATIVE_CODEBOOK = (
    CODEBOOK_DIR
    / "GSS_1972_2018_Codebook.pdf"
)

YEAR_CODEBOOKS = {
    2021: CODEBOOK_DIR / "GSS_2021_Codebook.pdf",
    2022: CODEBOOK_DIR / "GSS_2022_Codebook.pdf",
    2024: CODEBOOK_DIR / "GSS_2024_Codebook.pdf",
}


# ---------------------------------------------------------------------------
# Optional explicitly verified overrides
# ---------------------------------------------------------------------------
#
# Do NOT put guessed semantics here.
#
# This table is for cases where the official documentation has been manually
# checked but the PDF parser cannot recover the variable automatically.
#
# Example:
#
# VERIFIED_OVERRIDES = {
#     2021: {
#         "somevar": "Exact verified semantic description",
#     },
# }
#
# Leave empty until each remaining special variable has been checked.

VERIFIED_OVERRIDES: Dict[int, Dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Administrative/derived variables
# ---------------------------------------------------------------------------
#
# Same rule: only add entries after verifying what they mean.
#
# This separate provenance category allows us to distinguish a legitimate
# non-question model feature from a genuinely unresolved semantic variable.

ADMIN_METADATA_OVERRIDES: Dict[int, Dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def year_from_name(name: str) -> int:
    m = re.search(r"(19|20)\d{2}", name)

    if not m:
        raise ValueError(
            f"Cannot extract GSS year from {name!r}"
        )

    return int(m.group(0))


def semantic_norm(value: str) -> str:
    s = str(value or "").strip().lower()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)

    return re.sub(
        r"\s+",
        " ",
        s,
    ).strip()


def meaningful_semantic_text(
    variable: str,
    text: str,
    provenance: str = "",
) -> bool:
    """Whether text carries semantic information beyond the native name."""

    variable = str(variable or "").strip()
    text = str(text or "").strip()
    provenance = str(provenance or "").strip().upper()

    if not variable or not text:
        return False

    # Explicit fallback classifications must never be recycled as semantics.
    if provenance in {
        "NATIVE_NAME",
        "NATIVE LSM FEATURE NAME",
        "NATIVE_LSM_FEATURE_NAME",
    }:
        return False

    if semantic_norm(text) == semantic_norm(variable):
        return False

    # Reject codebook cross-reference text such as:
    #
    #   (No SCIBNFTSNV)
    #
    if re.fullmatch(
        r"\(?\s*No\s+[A-Za-z0-9_]+\s*\)?",
        text,
        re.I,
    ):
        return False

    return True


def read_semantic_map(
    path: Path,
) -> Dict[str, Tuple[str, str]]:
    """Read meaningful semantic entries from an existing canonical map.

    Returns
    -------
    variable_lower -> (text, provenance)
    """

    if not path.is_file():
        return {}

    try:
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
        )
    except Exception as e:
        print(
            f"WARNING: could not read semantic map "
            f"{path}: {e}"
        )
        return {}

    if "variable" not in df.columns:
        return {}

    text_col = next(
        (
            c
            for c in (
                "question_text_filled",
                "question_text",
                "variable_label",
            )
            if c in df.columns
        ),
        None,
    )

    if not text_col:
        return {}

    provenance_col = next(
        (
            c
            for c in (
                "map_provenance",
                "source",
            )
            if c in df.columns
        ),
        None,
    )

    out: Dict[str, Tuple[str, str]] = {}

    for _, row in df.iterrows():
        variable = str(
            row.get("variable", "")
        ).strip()

        text = str(
            row.get(text_col, "")
        ).strip()

        provenance = (
            str(
                row.get(
                    provenance_col,
                    "",
                )
            ).strip()
            if provenance_col
            else ""
        )

        if meaningful_semantic_text(
            variable,
            text,
            provenance,
        ):
            out[variable.lower()] = (
                text,
                provenance,
            )

    return out


def discover_existing_gss_maps(
    outdir: Path,
) -> Dict[int, Dict[str, Tuple[str, str]]]:
    """Snapshot every existing canonical map before rebuilding."""

    existing: Dict[
        int,
        Dict[str, Tuple[str, str]],
    ] = {}

    if not outdir.is_dir():
        return existing

    for path in sorted(
        outdir.glob("gss_*_map.csv")
    ):
        m = re.fullmatch(
            r"gss_(\d{4})_map\.csv",
            path.name,
        )

        if not m:
            continue

        year = int(m.group(1))

        semantic = read_semantic_map(
            path
        )

        if semantic:
            existing[year] = semantic

    return existing


def codebook_for_year(
    year: int,
) -> Optional[Path]:
    """Return the authoritative documentation source for a survey wave."""

    if year in YEAR_CODEBOOKS:
        return YEAR_CODEBOOKS[year]

    if year <= 2018:
        return CUMULATIVE_CODEBOOK

    return None


def load_codebook_lookup(
    path: Path,
) -> Dict[str, Tuple[str, str, str]]:
    """Parse one codebook.

    Returns
    -------
    variable_lower -> (semantic_text, page, parser_source)
    """

    docs = parse_codebook(path)

    lookup: Dict[
        str,
        Tuple[str, str, str],
    ] = {}

    for row in docs.itertuples(
        index=False
    ):
        variable = str(
            row.variable_key
        ).lower()

        text = norm(
            str(
                row.question_text
                or ""
            )
        )

        page = str(
            row.codebook_page
            or ""
        )

        parser_source = str(
            getattr(
                row,
                "codebook_source",
                "GSS_CODEBOOK",
            )
            or "GSS_CODEBOOK"
        )

        if usable_label(
            variable,
            text,
        ):
            lookup[variable] = (
                text,
                page,
                parser_source,
            )

    return lookup


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--model-root",
        default=str(
            model_path("gss")
        ),
        help=(
            "directory containing "
            "gss_YYYY native model directories"
        ),
    )

    ap.add_argument(
        "--outdir",
        default="maps/gss",
    )

    ap.add_argument(
        "--force",
        action="store_true",
    )

    args = ap.parse_args()

    def resolve_path(
        value: str,
    ) -> Path:
        p = Path(value).expanduser()

        if p.is_absolute():
            return p.resolve()

        return (
            ROOT / p
        ).resolve()

    model_root = resolve_path(
        args.model_root
    )

    outdir = resolve_path(
        args.outdir
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ------------------------------------------------------------------
    # Model inventory
    # ------------------------------------------------------------------

    if not model_root.is_dir():
        raise SystemExit(
            f"GSS model root does not exist: "
            f"{model_root}"
        )

    models = sorted(
        p
        for p in model_root.iterdir()
        if (
            p.is_dir()
            and re.fullmatch(
                r"gss_\d{4}",
                p.name,
            )
        )
    )

    if not models:
        raise SystemExit(
            "No gss_YYYY native model directories "
            f"under {model_root}"
        )

    print(
        f"native GSS models: "
        f"{len(models)}"
    )

    # ------------------------------------------------------------------
    # Snapshot existing maps BEFORE rewriting anything.
    # ------------------------------------------------------------------

    existing_by_year = (
        discover_existing_gss_maps(
            outdir
        )
    )

    donor_years = sorted(
        existing_by_year
    )

    print(
        "existing semantic donor years: "
        f"{donor_years}"
    )

    # ------------------------------------------------------------------
    # Validate expected codebooks.
    # ------------------------------------------------------------------

    print(
        "\nCODEBOOK INVENTORY"
    )

    print(
        f"1972-2018: "
        f"{'FOUND' if CUMULATIVE_CODEBOOK.is_file() else 'MISSING'} "
        f"{CUMULATIVE_CODEBOOK}"
    )

    for year, cb in sorted(
        YEAR_CODEBOOKS.items()
    ):
        print(
            f"{year}: "
            f"{'FOUND' if cb.is_file() else 'MISSING'} "
            f"{cb}"
        )

    # ------------------------------------------------------------------
    # Parse each documentation file only once.
    # ------------------------------------------------------------------

    codebook_paths = {
        cb
        for cb in (
            [CUMULATIVE_CODEBOOK]
            + list(
                YEAR_CODEBOOKS.values()
            )
        )
        if cb.is_file()
    }

    codebook_cache: Dict[
        Path,
        Dict[
            str,
            Tuple[str, str, str],
        ],
    ] = {}

    print(
        "\nPARSING CODEBOOKS"
    )

    for cb in sorted(
        codebook_paths,
        key=str,
    ):
        print(
            f"Parsing codebook once: "
            f"{cb}"
        )

        lookup = (
            load_codebook_lookup(cb)
        )

        codebook_cache[cb] = lookup

        print(
            "  meaningful variables: "
            f"{len(lookup)}"
        )

    # ------------------------------------------------------------------
    # Build maps.
    # ------------------------------------------------------------------

    summary = []

    print(
        "\nBUILDING MAPS"
    )

    for model_dir in models:
        year = year_from_name(
            model_dir.name
        )

        out = (
            outdir
            / f"gss_{year}_map.csv"
        )

        if (
            out.exists()
            and not args.force
        ):
            print(
                f"SKIP {year}: "
                f"{out} exists"
            )
            continue

        model = load_model(
            model_dir,
            backend="native_lsm",
            preload=False,
        )

        features = [
            str(x)
            for x in model.feature_names
        ]

        exact_year_existing = (
            existing_by_year.get(
                year,
                {},
            )
        )

        codebook_path = (
            codebook_for_year(
                year
            )
        )

        codebook_lookup = (
            codebook_cache.get(
                codebook_path,
                {},
            )
            if codebook_path
            else {}
        )

        rows = []

        counts = {
            "YEAR_CODEBOOK": 0,
            "CUMULATIVE_CODEBOOK": 0,
            "VERIFIED_OVERRIDE": 0,
            "ADMIN_METADATA": 0,
            "YEAR_SPECIFIC": 0,
            "DONOR_MAP": 0,
            "NATIVE_NAME": 0,
        }

        for variable in features:
            key = variable.lower()

            text = ""
            provenance = ""
            source_year = ""
            codebook_page = ""
            parser_source = ""

            # ------------------------------------------------------
            # 1. Authoritative codebook
            # ------------------------------------------------------

            cb = codebook_lookup.get(
                key
            )

            if cb:
                (
                    cb_text,
                    cb_page,
                    cb_parser_source,
                ) = cb

                if meaningful_semantic_text(
                    variable,
                    cb_text,
                ):
                    text = cb_text
                    codebook_page = cb_page
                    parser_source = (
                        cb_parser_source
                    )

                    if year in YEAR_CODEBOOKS:
                        provenance = (
                            "YEAR_CODEBOOK"
                        )
                        source_year = str(
                            year
                        )
                    else:
                        provenance = (
                            "CUMULATIVE_CODEBOOK"
                        )

            # ------------------------------------------------------
            # 2. Explicit manually verified exception
            # ------------------------------------------------------

            if not text:
                override = (
                    VERIFIED_OVERRIDES
                    .get(
                        year,
                        {},
                    )
                    .get(
                        key,
                        "",
                    )
                )

                if meaningful_semantic_text(
                    variable,
                    override,
                ):
                    text = override
                    provenance = (
                        "VERIFIED_OVERRIDE"
                    )
                    source_year = str(
                        year
                    )

            # ------------------------------------------------------
            # 3. Administrative/derived metadata description
            # ------------------------------------------------------

            if not text:
                admin = (
                    ADMIN_METADATA_OVERRIDES
                    .get(
                        year,
                        {},
                    )
                    .get(
                        key,
                        "",
                    )
                )

                if meaningful_semantic_text(
                    variable,
                    admin,
                ):
                    text = admin
                    provenance = (
                        "ADMIN_METADATA"
                    )
                    source_year = str(
                        year
                    )

            # ------------------------------------------------------
            # 4. Existing exact-year canonical semantic map
            # ------------------------------------------------------

            if not text:
                exact = (
                    exact_year_existing
                    .get(
                        key
                    )
                )

                if exact:
                    (
                        exact_text,
                        exact_provenance,
                    ) = exact

                    if meaningful_semantic_text(
                        variable,
                        exact_text,
                        exact_provenance,
                    ):
                        text = exact_text
                        provenance = (
                            "YEAR_SPECIFIC"
                        )
                        source_year = str(
                            year
                        )

            # ------------------------------------------------------
            # 5. Nearest exact-variable donor map
            # ------------------------------------------------------

            if not text:
                candidates = []

                for donor_year in donor_years:
                    if donor_year == year:
                        continue

                    rec = (
                        existing_by_year
                        .get(
                            donor_year,
                            {},
                        )
                        .get(
                            key
                        )
                    )

                    if not rec:
                        continue

                    (
                        donor_text,
                        donor_provenance,
                    ) = rec

                    if not meaningful_semantic_text(
                        variable,
                        donor_text,
                        donor_provenance,
                    ):
                        continue

                    candidates.append(
                        (
                            abs(
                                donor_year
                                - year
                            ),
                            donor_year,
                            donor_text,
                        )
                    )

                if candidates:
                    (
                        _,
                        donor_year,
                        donor_text,
                    ) = sorted(
                        candidates,
                        key=lambda x: (
                            x[0],
                            x[1],
                        ),
                    )[0]

                    text = donor_text
                    provenance = (
                        "DONOR_MAP"
                    )
                    source_year = str(
                        donor_year
                    )

            # ------------------------------------------------------
            # 6. Native-name fallback
            # ------------------------------------------------------

            if not text:
                text = variable
                provenance = (
                    "NATIVE_NAME"
                )

            counts[
                provenance
            ] += 1

            rows.append(
                {
                    "variable": variable,
                    "question_text": text,
                    "question_text_filled": text,
                    "source": provenance,
                    "source_year": source_year,
                    "codebook_page": codebook_page,
                    "codebook_source": parser_source,
                    "map_provenance": provenance,
                }
            )

        df = pd.DataFrame(
            rows
        )

        df.to_csv(
            out,
            index=False,
        )

        unresolved = (
            counts["NATIVE_NAME"]
        )

        resolved = (
            len(features)
            - unresolved
        )

        fraction = (
            resolved
            / max(
                1,
                len(features),
            )
        )

        print(
            f"GSS {year}: "
            f"vars={len(features)} "
            f"resolved={resolved} "
            f"({fraction:.4f}) "
            f"year_cb="
            f"{counts['YEAR_CODEBOOK']} "
            f"cum_cb="
            f"{counts['CUMULATIVE_CODEBOOK']} "
            f"override="
            f"{counts['VERIFIED_OVERRIDE']} "
            f"admin="
            f"{counts['ADMIN_METADATA']} "
            f"existing="
            f"{counts['YEAR_SPECIFIC']} "
            f"donor="
            f"{counts['DONOR_MAP']} "
            f"native="
            f"{counts['NATIVE_NAME']}"
        )

        summary.append(
            {
                "year": year,
                "variables": len(
                    features
                ),
                "year_codebook": counts[
                    "YEAR_CODEBOOK"
                ],
                "cumulative_codebook": counts[
                    "CUMULATIVE_CODEBOOK"
                ],
                "verified_override": counts[
                    "VERIFIED_OVERRIDE"
                ],
                "admin_metadata": counts[
                    "ADMIN_METADATA"
                ],
                "year_specific": counts[
                    "YEAR_SPECIFIC"
                ],
                "donor_map": counts[
                    "DONOR_MAP"
                ],
                "native_name": counts[
                    "NATIVE_NAME"
                ],
                "resolved_fraction": fraction,
                "codebook": (
                    str(codebook_path)
                    if codebook_path
                    else ""
                ),
                "out": str(out),
            }
        )

    # ------------------------------------------------------------------
    # Build report
    # ------------------------------------------------------------------

    report = (
        ROOT
        / "outputs"
        / "gss_native_map_build_report.csv"
    )

    report.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_df = pd.DataFrame(
        summary
    )

    if not report_df.empty:
        report_df = (
            report_df
            .sort_values(
                "year"
            )
        )

    report_df.to_csv(
        report,
        index=False,
    )

    print(
        f"\nreport: {report}"
    )

    if report_df.empty:
        return

    print(
        "\nSEMANTIC COVERAGE SUMMARY"
    )

    print(
        report_df[
            [
                "year",
                "variables",
                "year_codebook",
                "cumulative_codebook",
                "verified_override",
                "admin_metadata",
                "year_specific",
                "donor_map",
                "native_name",
                "resolved_fraction",
            ]
        ].to_string(
            index=False
        )
    )

    print(
        "\nLOWEST-COVERAGE WAVES"
    )

    print(
        report_df[
            [
                "year",
                "variables",
                "native_name",
                "resolved_fraction",
            ]
        ]
        .sort_values(
            "resolved_fraction"
        )
        .head(10)
        .to_string(
            index=False
        )
    )

    # ------------------------------------------------------------------
    # Explicit unresolved-variable report
    # ------------------------------------------------------------------

    print(
        "\nUNRESOLVED VARIABLES"
    )

    total_unresolved = 0

    for year in sorted(
        report_df["year"]
    ):
        path = (
            outdir
            / f"gss_{int(year)}_map.csv"
        )

        d = pd.read_csv(
            path,
            dtype=str,
        ).fillna("")

        unresolved_df = d[
            d["map_provenance"]
            == "NATIVE_NAME"
        ]

        if unresolved_df.empty:
            continue

        total_unresolved += len(
            unresolved_df
        )

        print(
            f"\nGSS {int(year)}: "
            f"{len(unresolved_df)}"
        )

        for variable in (
            unresolved_df["variable"]
            .astype(str)
            .tolist()
        ):
            print(
                f"  {variable}"
            )

    print(
        f"\nTOTAL UNRESOLVED: "
        f"{total_unresolved}"
    )


if __name__ == "__main__":
    main()
