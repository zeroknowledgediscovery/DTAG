#!/usr/bin/env python3
"""Read one private DTAG final.json and audit respondent-visible question wording.

Runs offline after data have been downloaded or streamed from private GCS.
Does NOT print participant answers, session identifiers, ideology scores or policy.
This is a screening report, NOT a substitute for instrument/source review.
Usage:
  gcloud storage cat gs://BUCKET/studies/pilot-001/sessions/SESSION/final.json \
    | python3 human_study/scripts/audit_completed_questions.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys


NUMERIC_LABEL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
RANK_LABEL = re.compile(r"\b(?:[1-5](?:st|nd|rd|th)|second|third|fourth|least) (?:most )?important\b", re.I)
UNJOINED_STEM = re.compile(r"\?\)\s*\S+")
SOURCE_FRAGMENT = re.compile(r"^\s*\((?:i am going|as far as|\.{2,})", re.I)
TRUNCATION_END = re.compile(
    r"(?:\b(?:the government should|other people t|others think that|still others|the woman takes care of the|financial inst)\s*$|\.{3}\s*$)",
    re.I,
)
RANKING_ITEMS = {"workhard", "helpoth"}


def audit(final):
    """Return only instrument metadata and observed display strings, never answers."""
    source_items = {item["item_id"]: item for item in final["study_configuration"]["items"]}
    rows = []
    for q in sorted(final["questions"], key=lambda x: x["ordinal"]):
        var = q["target_variable"]
        item = source_items.get(var, {})
        raw = q.get("original_wording", item.get("original_wording", ""))
        shown = str(q.get("displayed_wording") or "").strip()
        choices = q.get("choices", item.get("choices", []))
        labels = [str(c.get("display_label", "")) for c in choices]
        provenance = q.get("question_provenance") or {}
        incomplete = bool(item.get("source_text_incomplete", False))
        issues = []

        def flag(category, reason):
            issues.append({"severity": category, "reason": reason})

        looks_like_source = (
            bool(UNJOINED_STEM.search(shown)) or
            bool(SOURCE_FRAGMENT.search(shown)) or
            bool(TRUNCATION_END.search(shown))
        )
        if not shown:
            flag("FAIL", "MISSING_DISPLAY_TEXT")
        if looks_like_source:
            flag("FAIL", "UNJOINED_OR_TRUNCATED_SOURCE_VISIBLE")
        if incomplete and shown == raw.strip():
            flag("FAIL", "INCOMPLETE_SOURCE_SHOWN_VERBATIM")
        if var == "confinan" and not re.search(r"\bbanks?\b|\bfinancial institutions?\b", shown, re.I):
            flag("FAIL", "INSTITUTION_MISSING_FROM_CONFIDENCE_QUESTION")
        if provenance.get("fallback") and incomplete:
            flag("FAIL", "INCOMPLETE_SOURCE_FALLBACK")
        elif provenance.get("fallback"):
            flag("REVIEW", "GENERATED_QUESTION_FALLBACK")
        if incomplete and provenance.get("validation_method") != "verified_2024_form_specific_reference_v1":
            flag("REVIEW", "SOURCE_EXCERPT_NOT_INDEPENDENTLY_VERIFIED")
        if shown and not shown.endswith("?"):
            flag("REVIEW", "NO_TERMINAL_QUESTION_MARK")
        if any(NUMERIC_LABEL.fullmatch(label.strip()) for label in labels):
            flag("FAIL", "UNEXPLAINED_NUMERIC_RESPONSE_LABELS")
        if var in RANKING_ITEMS or any(RANK_LABEL.search(label) for label in labels):
            flag("FAIL", "RANKING_REQUIRES_COMPLETE_COMPARATIVE_TASK")
        if q.get("phase") == "intervention" and not provenance.get("fallback") and (
            provenance.get("provider") == "openai" and
            not provenance.get("mapper_hit") and
            provenance.get("validation_method") != "verified_2024_form_specific_reference_v1"
        ):
            flag("REVIEW", "GENERATED_QUESTION_NOT_REVERSE_VALIDATED")

        rows.append({
            "number": int(q["ordinal"]) + 1,
            "phase": q["phase"],
            "variable": var,
            "displayed_wording": shown,
            "original_wording": raw,
            "answer_labels": labels,
            "source_text_incomplete": incomplete,
            "provider": provenance.get("provider", "unknown"),
            "fallback": bool(provenance.get("fallback")),
            "mapper_hit": bool(provenance.get("mapper_hit")),
            "validation_method": provenance.get("validation_method"),
            "source_reference": provenance.get("source_reference"),
            "issues": issues,
        })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="path to final.json; '-' for stdin")
    parser.add_argument("--show-original", action="store_true", help="print source text alongside displayed text")
    parser.add_argument("--json", action="store_true", help="structured audit report (no participant answers)")
    parser.add_argument("--fail-on-issues", action="store_true", help="exit 2 on a FAIL issue")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            final = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as stream:
                final = json.load(stream)
        rows = audit(final)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"invalid final.json: {exc}")
    counts = {
        "questions": len(rows),
        "flagged": sum(bool(r["issues"]) for r in rows),
        "fail": sum(any(i["severity"] == "FAIL" for i in r["issues"]) for r in rows),
        "review": sum(any(i["severity"] == "REVIEW" for i in r["issues"]) for r in rows),
    }
    if args.json:
        json.dump({"summary": counts, "questions": rows}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Question audit: {counts['questions']} presented; "
              f"{counts['flagged']} flagged; {counts['fail']} FAIL; {counts['review']} REVIEW")
        print("Flags screen wording and scales only; check all questions against official 2024 ballot.")
        for r in rows:
            issues = ", ".join(f"{i['severity']}:{i['reason']}" for i in r["issues"]) or "none"
            print(f"\n{r['number']:02d} [{r['phase']}] {r['variable']} :: {issues}")
            print(f"  SHOWN: {r['displayed_wording']}")
            print(f"  CHOICES: {' | '.join(r['answer_labels'])}")
            print(f"  PROVENANCE: {r['provider']}; fallback={r['fallback']}; "
                  f"mapper_hit={r['mapper_hit']}; validation={r['validation_method'] or 'unspecified'}")
            if args.show_original:
                print(f"  SOURCE: {r['original_wording']}")
    return 2 if args.fail_on_issues and counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
