#!/usr/bin/env python3
"""Compile post-selection wording for all 811 model coordinates, fail-closed.

Default: package only source-contract-backed wording; enumerate/report EVERY
other native feature with the exact reason it needs further documentation.
Optionally create *unapproved* LLM draft questions for offline researcher
review. Drafts NEVER enter the runtime catalog without explicit source review.
No model optimization, selection, eligibility, or free-text mapping is changed.

Input is the actual native-model audit JSON produced with the official 2024
codebook by human_study/scripts/audit_all_native_gss_2024.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "human_study" / "backend"))

from human_study.compiled_wording import (
    CATALOG_PATH, MODEL_RELEASE, entry_for, fingerprint,
)
from human_study.grounded_generation import (
    craft_question, has_unresolved_choice_reference, validate_complete_choices,
)
from human_study.wording_contracts import (
    context_for_native_item, validates_standalone, validates_wording,
)


def make_item(row):
    return SimpleNamespace(
        item_id=row["variable"],
        original_wording=row["semantic_map_question"],
        source_text_incomplete=True,
        version="native-map-runtime",
        choices=tuple(SimpleNamespace(native_value=str(x), display_label=str(x))
                      for x in row["native_supported_answers"]),
    )


def validation_errors(item, question):
    errors = []
    if not validates_standalone(question):
        errors.append("invalid_or_dependent_standalone_wording")
    contract = context_for_native_item(
        item.item_id, [c.display_label for c in item.choices],
    )
    if contract and not validates_wording(
        item.item_id, question, contract_override=contract,
    ):
        errors.append("missing_source_contract_referent_or_scale")
    source = contract.source if contract else item.original_wording
    missing = validate_complete_choices(question, source, item.choices)
    if missing:
        errors.append(f"missing_native_response_labels:{len(missing)}")
    if has_unresolved_choice_reference(question, source, item.choices):
        errors.append("unresolved_reference_or_hidden_card")
    return errors


def compile_inventory(audit, approved=None):
    """Deterministic no-LLM compilation of pre-restored source contracts.

    A researcher-reviewed wording entry must carry explicit identity hashes
    and a review reference; a mere syntactically valid LLM draft is rejected.
    """
    summary = audit["summary"]
    rows = audit["variables"]
    if (summary.get("model_key") != "gss/gss_2024"
            or summary.get("total_native_model_variables") != 811
            or summary.get("semantic_map_matched") != 811
            or len(rows) != 811
            or len({r["variable"] for r in rows}) != 811):
        raise ValueError("must compile complete 811-variable native model, not a candidate subset")
    approved = approved or {}
    catalog = {}
    status = []
    for row in rows:
        item = make_item(row)
        contract = context_for_native_item(
            item.item_id, [c.display_label for c in item.choices],
        )
        text = contract.source if contract else ""
        cert = "source_contract" if contract else None
        reference = contract.source_reference if contract else None
        manual = approved.get(item.item_id)
        if manual:
            # This is a separate, opt-in researcher action; do not treat
            # automatic LLM output or a codebook label as review approval.
            if not isinstance(manual, dict) or not manual.get("reviewer") or not manual.get("source_reference"):
                raise ValueError(f"{item.item_id}: reviewer and source_reference required")
            if manual.get("source_map_sha256") != fingerprint(item.original_wording):
                raise ValueError(f"{item.item_id}: source map changed since review")
            if manual.get("native_answers_sha256") != fingerprint(
                [c.native_value for c in item.choices]
            ):
                raise ValueError(f"{item.item_id}: native alphabet changed since review")
            text = str(manual["question"])
            cert = "human_reviewed"
            reference = str(manual["source_reference"])
        problems = validation_errors(item, text) if text else ["no_validated_wording"]
        if cert and not problems:
            entry = entry_for(item, text, certification=cert, source_reference=reference)
            if cert == "human_reviewed":
                entry["reviewer"] = manual["reviewer"]
                entry["review_notes"] = manual.get("review_notes", "")
            catalog[item.item_id] = entry
        status.append({
            "variable": item.item_id,
            "status": cert if cert and not problems else "needs_source_review",
            "source_contract_present": bool(contract),
            "codebook_entry_found": bool(row.get("codebook_entry_found")),
            "review_flags": row.get("flags", []),
            "validation_failures": problems,
        })
    catalog = dict(sorted(catalog.items()))
    rev = fingerprint(catalog)
    obj = {
        "schema_version": "1",
        "model_key": "gss/gss_2024",
        "model_release": MODEL_RELEASE,
        "total_native_variables": 811,
        "catalog_revision_sha256": rev,
        "entries": catalog,
    }
    report = {
        "schema_version": "1",
        "native_variable_count": 811,
        "precompiled_count": len(catalog),
        "source_contract_compiled": sum(e["certification"] == "source_contract"
                                        for e in catalog.values()),
        "human_reviewed_compiled": sum(e["certification"] == "human_reviewed"
                                      for e in catalog.values()),
        "live_llm_fallback_count": 811 - len(catalog),
        "qualifications": status,
    }
    return obj, report


def prepare_draft(row, client, model, *, attempts=2):
    """Generate only a candidate for researcher review (never auto-publish)."""
    item = make_item(row)
    contract = context_for_native_item(
        item.item_id, [c.display_label for c in item.choices],
    )
    source = contract.source if contract else item.original_wording
    feedback = []
    errors = []
    result = None
    for _ in range(attempts):
        result = craft_question(
            client, model, item.item_id, item.original_wording, source,
            [c.display_label for c in item.choices],
            contract_reference=contract.source_reference if contract else None,
            feedback=feedback,
        )
        if result["missing_context"]:
            errors = ["original_source_context_missing"]
            feedback = [str(result["missing_details"])[:300]]
            continue
        errors = validation_errors(item, result["question"])
        if not errors:
            break
        feedback = errors
    return {
        "variable": item.item_id,
        "source_map_sha256": fingerprint(item.original_wording),
        "native_answers_sha256": fingerprint(
            [c.native_value for c in item.choices]
        ),
        "proposed_question": result["question"] if result else "",
        "source_map_text": item.original_wording,
        "native_answers": [c.native_value for c in item.choices],
        "source_reference": contract.source_reference if contract else None,
        "codebook_entry_found": row.get("codebook_entry_found"),
        "validation_failures": errors,
        "publication_status": "unapproved_researcher_review_required",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    parser.add_argument("--reviewed-json", type=Path, default=None)
    parser.add_argument("--generate-drafts", action="store_true",
                        help="make LIVE OpenAI calls for all unresolved items, drafts only")
    parser.add_argument("--draft-limit", type=int, default=0,
                        help="number of unresolved variables to draft; 0 means all")
    parser.add_argument("--drafts-out", type=Path, default=None)
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()
    audit = json.loads(args.audit_json.read_text(encoding="utf-8"))
    approved = (json.loads(args.reviewed_json.read_text(encoding="utf-8"))
                if args.reviewed_json else {})
    if not isinstance(approved, dict):
        raise ValueError("reviewed-json must be an object keyed by variable")
    catalog, report = compile_inventory(audit, approved)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status_path = args.out.with_suffix(".coverage.json")
    status_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Native coordinates: 811; compiled: {len(catalog['entries'])}; "
          f"LLM fallback: {811-len(catalog['entries'])}")
    print(f"Catalog: {args.out} | Coverage: {status_path}")
    if args.generate_drafts:
        # Draft mode is a deliberate separately invoked offline workflow and
        # cannot mark generated strings reviewed or update published catalog.
        from openai import OpenAI
        client = OpenAI(timeout=45, max_retries=0)
        rows = [r for r in audit["variables"] if r["variable"] not in catalog["entries"]]
        if args.draft_limit > 0:
            rows = rows[:args.draft_limit]
        drafts = []
        for i, row in enumerate(rows, 1):
            try:
                draft = prepare_draft(row, client, args.model)
            except Exception as exc:
                draft = {"variable": row["variable"],
                         "validation_failures": [type(exc).__name__],
                         "publication_status": "unapproved_researcher_review_required"}
            drafts.append(draft)
            if i % 25 == 0:
                print(f"drafts {i}/{len(rows)}", flush=True)
        dest = args.drafts_out or args.out.with_suffix(".drafts.json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(drafts, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"Unapproved LLM drafts: {dest}")


if __name__ == "__main__":
    main()
