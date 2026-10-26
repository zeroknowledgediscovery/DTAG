#!/usr/bin/env python3
"""Read-only, broader standalone-wording audit for the 2024 GSS opinion map.

Unlike audit_gss_wording_map.py, this screens short semantic labels, shared
ranking batteries, omitted answer alternatives, truncated stems, and opinion
eligibility as well as overt source markup. This is triage, NOT certification
that every question can be displayed correctly.

By default, asks "which rows pass the native webapp's *static* askable
predicate" with all CSV IDs as provisional feature names. Native model
indexability, supported answer labels, pole items, and actual feat membership
are NOT established by static mode. Use --native-candidates on a configured
model host to enumerate the actual empty-state pool.

Nothing here changes the candidate pool, source map, wording, or LSM.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from human_study.study_config import StudyConfig
from human_study.wording_contracts import CONTRACTS

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "maps/gss/gss_2024_map.csv"
CONFIG = ROOT / "human_study/config/study.prolific.gcptest.yaml"

# These are verified examples, not a claim that every other entry is correct.
# NORC GSS 2024 R2 codebook pages 150-153, 142-146, 186, 206-211, 355,
# 428; questionnaire forms establish the dependent stems and alternatives.
CONFIRMED_SOURCE_INCOMPLETE = {
    "obey", "popular", "thnkself", "workhard", "helpoth",  # same ranked card A9
    "polescap", "confinan", "confed",
    "letin1", "letin1a", "pornlaw",
    "marblk", "marasian", "marhisp",
    "rateincumb24", "ratechall124", "ratechall224", "ratechall324",
    "ratedemp", "raterepp", "ratemaga",
}
# Screening items that should prompt a *separate* eligibility assessment.
# No modification to the optimized candidate universe is authorized here.
POSSIBLE_NON_OPINION = {
    "hrs1", "hrs2", "sphrs1", "spwrksta", "reg16", "mobile16",
    "rincom16", "health", "happy", "life", "jobfind", "parsol",
    "kidssol", "posslq", "sexornt", "sexbirth1", "dwelown16",
    "spklang", "relpersn", "relactiv",
}
DEPENDENT = re.compile(
    r"^(?:was (?:attempting|being)|had (?:said|done)|"
    r"to (?:obey|think|be|work|help)|what about\b|how about\b|"
    r"if \b|after\b|which of these|which of the following|"
    r"now we would like|about how often|how well do you speak that language)",
    re.I,
)
BROKEN_END = re.compile(
    r"(?:\b(?:to|the|th|of|and|or|be|should be|because|while|like|for|about)\b|"
    r"[,;:\-\u2013])\s*[.?!]?\s*$", re.I
)
REFERENT = re.compile(
    r"(?:\b(?:such|this|those|these)\s+(?:person|people|things|questions|"
    r"institutions?|statements?|group|ones?)\b|"
    r"\b(?:R|respondent)\s+(?:has|is|worried|satisfied|would|thinks)\b)",
    re.I,
)
SOURCE_MARKUP = re.compile(
    r"\.{3,}|…|\{[A-Z0-9_]+\}|\[(?:IF|the last|R's)\b|"
    r"\bIF (?:WORKING|WITH A JOB|STATE)\b|\(OCC\)|"
    r"\b(?:READ CATEGORIES|USE CATEGORIES AS PROBES)\b",
    re.I,
)
SCALE_REFERENCE = re.compile(
    r"(?:which of these statements|which of the following|"
    r"on a \d+-point scale|rating of |\btrust in .*, \d+ point scale\b|"
    r"^reliability of |\bspecific scales?\b)",
    re.I,
)
QUICK_LABEL = re.compile(
    r"^(?:how important(?::|\b)|how well (?:does|did|will)|"
    r"agree\b|rate\b|rating\b|reliability of|importance of|"
    r"government'?s responsibility|would R\b|R worried|"
    r"the people, not |immigrants? |international bodies |"
    r"american? should |america should |family life |"
    r"best if |public service )", re.I,
)


def signals(source: str) -> list[str]:
    text = source.strip()
    nwords = len(text.split())
    found = []
    if nwords <= 12 and "?" not in text:
        found.append("short_label")
    if "?" not in text:
        found.append("not_a_complete_question")
    if DEPENDENT.search(text):
        found.append("dependent_stem")
    if BROKEN_END.search(text):
        found.append("broken_ending")
    if REFERENT.search(text):
        found.append("unresolved_reference_risk")
    if SOURCE_MARKUP.search(text):
        found.append("source_markup")
    if SCALE_REFERENCE.search(text):
        found.append("unseen_scale_or_alternatives")
    if QUICK_LABEL.search(text):
        found.append("abbreviated_response_task")
    return found


def load_rows():
    with MAP.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def static_pool(rows):
    # Reuse the REAL webapp filter, not an imitation of its regexes.
    # Only its feat-dependent suffix suppression uses this provisional set.
    from optimize_question_sets import askable
    feat = {r["variable"] for r in rows}
    return {
        r["variable"] for r in rows
        if askable(
            r["variable"],
            r.get("question_text_filled") or r.get("question_text") or "",
            feat,
        )
    }


def inspect(rows, *, candidate_ids=None):
    if candidate_ids is None:
        candidate_ids = static_pool(rows)
    for row in rows:
        v = row["variable"]
        text = (row.get("question_text_filled") or
                row.get("question_text") or "").strip()
        detected = signals(text)
        contracted = v in CONTRACTS
        # NATENVIY has a separate 2024 form-specific anchor in questions.py
        # that must be validated against its actual native answer labels.
        anchored = v == "natenviy"
        if v in CONFIRMED_SOURCE_INCOMPLETE and not contracted:
            priority = "P0_verified_incomplete"
        elif v in POSSIBLE_NON_OPINION and not contracted:
            priority = "P1_eligibility_review"
        elif not contracted and not anchored and detected:
            priority = "P1_source_review"
        elif not contracted and not anchored:
            priority = "P2_no_contract_review"
        else:
            priority = "contracted_or_anchored"
        yield {
            "variable": v,
            "static_or_native_candidate": v in candidate_ids,
            "contracted": contracted,
            "special_source_anchor": anchored,
            "priority": priority,
            "signals": detected,
            "codebook_page": row.get("codebook_page", ""),
            "original_source": text,
        }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--native-candidates", action="store_true",
                   help="use actual configured GSS model and empty-state webapp candidates")
    p.add_argument("--out", type=Path, help="save complete row-by-row JSON report")
    p.add_argument("--compact", action="store_true",
                   help="print only priority counts and P0 verified defects")
    args = p.parse_args()
    rows = load_rows()
    if args.native_candidates:
        from human_study.adapter import NativeAdapter
        cfg = StudyConfig.load(CONFIG)
        candidates = set(NativeAdapter(cfg).webapp_candidates({}, cfg))
        mode = "actual_native_empty_state"
    else:
        candidates = static_pool(rows)
        mode = "static_webapp_filter_approximation"
    result = list(inspect(rows, candidate_ids=candidates))
    selected = [r for r in result if r["static_or_native_candidate"]]
    counts = Counter(r["priority"] for r in selected)
    summary = {
        "schema_version": "1",
        "mode": mode,
        "map_rows": len(result),
        "candidate_rows": len(selected),
        "contracted_or_anchored": counts["contracted_or_anchored"],
        "uncontracted_candidate_rows": len(selected) - counts["contracted_or_anchored"],
        "priorities": dict(sorted(counts.items())),
        "note": "Signals denote review requirements, not confirmed defective live questions.",
    }
    print(json.dumps(summary, indent=2))
    for r in selected:
        if r["priority"] == "P0_verified_incomplete" or (
            not args.compact and r["priority"] != "contracted_or_anchored"
        ):
            print(
                f"{r['priority']:28} {r['variable']:14} "
                f"{','.join(r['signals'])[:68]:68} "
                f"{r['original_source'][:130]}"
            )
    if args.out:
        args.out.write_text(json.dumps({
            "summary": summary,
            "candidate_rows": selected,
            "other_map_rows": [r for r in result if not r["static_or_native_candidate"]],
        }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
