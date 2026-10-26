#!/usr/bin/env python3
"""Exhaustive native GSS-2024 question-documentation audit (NO candidate filtering).

The inventory is keyed to *every source_maps native model feature*, not the
empty-state webapp subset, YAML instrument, or GSS semantic-map row count.

For each variable reports its original semantic-map text, native alphabet,
source-specific wording contract (if any), source-document entry (if provided),
context/response/applicability risks, and verification status.

Counts and pending statuses are explicit: automated scanning is NOT a
substitute for reviewing the 2024 GSS codebook/ballots, nor is a fluent
question proof of response-code equivalence. No model science is changed.

Usage, from repo root:
  PYTHONPATH=human_study/backend:scripts python3 \
    human_study/scripts/audit_all_native_gss_2024.py --out /tmp/gss-all
  PYTHONPATH=human_study/backend:scripts python3 \
    human_study/scripts/audit_all_native_gss_2024.py \
    --codebook /path/to/GSS_2024_Codebook_R2.pdf --out /tmp/gss-all

The model is installed through DTAG's *original* ensure_model resolver. No
native LSM C++ runtime is needed: source_maps contain the 811 alphabets.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "human_study" / "backend"))

from human_study.wording_contracts import CONTRACTS
from audit_standalone_candidates import (
    CONFIRMED_SOURCE_INCOMPLETE,
    POSSIBLE_NON_OPINION,
    signals,
)

RELEASE_CODEBOOK = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/"
    "codebook/GSS%202024%20Codebook%20R2.pdf"
)
STUDY_MODEL = "gss/gss_2024"
RELEASE_FEATURE_COUNT = 811

# Human-readable reserved nonresponses in official GSS data. They may be
# present in native alphabets; they are *not* ordinary survey answer options.
RESERVED = re.compile(
    r"^(?:i?a?p|iap|dk|na|n/a|d/k|don't know|dont know|do not know|"
    r"no answer|not applicable|not available|refus(?:ed|al)|"
    r"skipped|not on web|not on ballot)\b",
    re.I,
)
RANGE_QUESTION = re.compile(
    r"\b(?:following|these|the|which)\s+(?:income |earnings? )?"
    r"(?:groups?|ranges?|brackets?|statements?|alternatives?|options?)\b",
    re.I,
)
DEPENDENT_BATTERY = re.compile(
    r"\b(?:first|second|third) mention\b|"
    r"\b(?:after \{[^}]+\}|(?:if|only) (?:you|the respondent)|"
    r"ask only|not applicable|showcard|ranking|ranked)\b",
    re.I,
)


def _native_inventory(model_root: Path):
    """Use official DTAG column reader: native names and categorical support."""
    from model_backend import _read_native_columns
    names, per_column = _read_native_columns(model_root)
    if len(set(names)) != len(names):
        raise ValueError("model has duplicate native feature names")
    return [(v, [str(x) for x in per_column.get(i, [])])
            for i, v in enumerate(names)]


def load_map(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return {r["variable"]: r for r in csv.DictReader(f)}


def parse_codebook_text_pages(pages):
    """Extract all R2 codebook variable entries, including page continuations.

    Tolerates repeated 'Variable: X' headers on continuing pages and emits
    exact page IDs and text blocks. Keep raw block for manual verification.
    It is intentionally conservative: a parsed source is not certified
    complete until its shared questionnaire stem and options are reviewed.
    """
    by_var = defaultdict(lambda: {"pages": [], "blocks": []})
    for page_number, text in pages:
        text = text or ""
        matches = list(re.finditer(
            r"(?m)^\s*Variable:\s*([A-Za-z0-9_]+)\s+Type:\s*\w+",
            text,
        ))
        for idx, m in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            var = m.group(1).casefold()
            block = text[m.start():end].strip()
            obj = by_var[var]
            if page_number not in obj["pages"]:
                obj["pages"].append(page_number)
            obj["blocks"].append(block)
    return dict(by_var)


def load_codebook_pdf(path):
    import pdfplumber
    with pdfplumber.open(path) as doc:
        return parse_codebook_text_pages(
            (i + 1, page.extract_text() or "")
            for i, page in enumerate(doc.pages)
        )


def map_source(row):
    if not row:
        return ""
    return str(row.get("question_text_filled") or row.get("question_text") or "").strip()


def audit_all(native_features, semantic_map, *, codebook=None):
    """Return one row per model feature; never apply askable/pole exclusions."""
    codebook = codebook or {}
    output = []
    for position, (variable, values) in enumerate(native_features):
        row = semantic_map.get(variable)
        raw = map_source(row)
        contract = CONTRACTS.get(variable.casefold())
        book = codebook.get(variable.casefold())
        book_text = "\n".join(book.get("blocks", [])) if book else ""
        # Strip the frequency/reserved-code table. Nearly every GSS item
        # contains a statistical "NOT APPLICABLE" row, which is not evidence
        # of a questionnaire skip instruction for that question.
        book_stem = "\n".join(
            re.split(r"(?m)^\s*(?:PCT Excl\.|LABEL VALUE|RESERVED CODES:)",
                     block, maxsplit=1)[0]
            for block in book.get("blocks", [])
        ) if book else ""
        flags = []
        if not row:
            flags.append("model_variable_missing_semantic_map")
        if not raw:
            flags.append("missing_question_text")
        flags += ["map_" + code for code in signals(raw)]
        if variable in CONFIRMED_SOURCE_INCOMPLETE and contract is None:
            flags.append("previously_verified_incomplete_source")
        if variable in POSSIBLE_NON_OPINION:
            flags.append("eligibility_or_respondent_fact_requires_review")
        if len(values) < 2:
            flags.append("native_alphabet_has_fewer_than_two_categories")
        if any(RESERVED.match(v.strip()) for v in values):
            flags.append("native_support_contains_reserved_or_not_applicable_values")
        if RANGE_QUESTION.search(raw):
            flags.append("source_references_external_choices")
        if DEPENDENT_BATTERY.search(raw + " " + book_stem):
            flags.append("dependent_stem_or_routing_requires_review")
        if codebook and not book:
            flags.append("not_found_in_supplied_codebook")
        if contract:
            if not contract.source:
                flags.append("contract_source_empty")
            if not contract.required_patterns:
                flags.append("contract_has_no_semantic_guards")
            if RANGE_QUESTION.search(contract.source):
                flags.append("review_contract_response_scale_against_native_values")

        # Human review is separate from automated coverage. A codebook entry
        # and a contract alone are not proof of the right ballot, conditioning,
        # response scale, or native value mapping. No fake "pass" statuses.
        output.append({
            "native_index": position, "variable": variable,
            "native_supported_answers": values,
            "native_supported_answer_count": len(values),
            "semantic_map_present": bool(row),
            "semantic_map_question": raw,
            "semantic_map_codebook_page": (row or {}).get("codebook_page", ""),
            "source_contract_present": bool(contract),
            "source_contract_question": contract.source if contract else None,
            "source_contract_reference": contract.source_reference if contract else None,
            "codebook_entry_found": bool(book),
            "codebook_pdf_pages": book.get("pages", []) if book else [],
            "codebook_entry_text": book_text or None,
            "codebook_label_and_notes": book_stem or None,
            "flags": sorted(set(flags)),
            "manual_checks_required": [
                "verify_complete_standalone_question_and_referents",
                "verify_native_values_match_original_response_categories",
                "verify_routing_and_applicability",
                "verify_original_questionnaire_form_and_scale",
            ],
            "source_certification": "pending_independent_review",
        })
    return output


def summarize(rows, model_key=STUDY_MODEL):
    counts = Counter(flag for row in rows for flag in row["flags"])
    return {
        "schema_version": "1",
        "model_key": model_key,
        "total_native_model_variables": len(rows),
        "expected_native_model_variables": RELEASE_FEATURE_COUNT,
        "all_native_variables_enumerated": len(rows) == RELEASE_FEATURE_COUNT,
        "semantic_map_matched": sum(r["semantic_map_present"] for r in rows),
        "source_contracts_present": sum(r["source_contract_present"] for r in rows),
        "source_codebook_entries_matched": sum(r["codebook_entry_found"] for r in rows),
        "no_native_answer_support": sum(not r["native_supported_answers"] for r in rows),
        "manual_source_certifications_complete": 0,
        "flag_totals": dict(sorted(counts.items())),
        "scope": "every native GSS 2024 feature, without askable or policy filtering",
        "qualification": "INCOMPLETE: all entries require original-form and answer-code review",
    }


def run():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-root", type=Path,
                   help="native model directory containing source_maps/ and trees/binary/")
    p.add_argument("--codebook", type=Path,
                   help="local original 2024 R2 codebook PDF (optional)")
    p.add_argument("--out", type=Path, default=Path("/tmp/dtag-gss2024-all"),
                   help="path prefix for .json/.csv outputs")
    p.add_argument("--fail-unqualified", action="store_true",
                   help="fail CI unless every entry has been independently certified")
    args = p.parse_args()

    if args.model_root:
        model_root = args.model_root
    else:
        from optimizer.dtag_bridge import ensure_model
        model_root = ensure_model(STUDY_MODEL, None)
    names = _native_inventory(model_root)
    if len(names) != RELEASE_FEATURE_COUNT:
        raise SystemExit(
            f"Model source-map feature mismatch: got {len(names)}, "
            f"expected {RELEASE_FEATURE_COUNT}; do not audit a different release."
        )
    mapping = load_map(ROOT / "maps" / "gss" / "gss_2024_map.csv")
    codebook = load_codebook_pdf(args.codebook) if args.codebook else None
    rows = audit_all(names, mapping, codebook=codebook)
    result = {"summary": summarize(rows), "variables": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with args.out.with_suffix(".csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        fields = (
            "native_index", "variable", "native_supported_answer_count",
            "native_supported_answers", "semantic_map_present",
            "semantic_map_question", "semantic_map_codebook_page",
            "source_contract_present", "source_contract_question",
            "source_contract_reference", "codebook_entry_found",
            "codebook_pdf_pages", "flags", "source_certification",
        )
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=False)
                             if isinstance(row[k], list) else row[k]
                             for k in fields})
    print(json.dumps(result["summary"], indent=2))
    print(f"Full inventory: {args.out.with_suffix('.json')}")
    print(f"Review table:   {args.out.with_suffix('.csv')}")
    if args.fail_unqualified:
        raise SystemExit("FAIL: full human-source certification remains incomplete")


if __name__ == "__main__":
    run()
