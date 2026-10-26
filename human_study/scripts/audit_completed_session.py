#!/usr/bin/env python3
"""Inspect one completed DTAG final.json WITHOUT exposing respondent text.

Reports repeated GSS target IDs, known respondent-facing question families,
identical generated question wording, and generation failures that eventually
recovered or were auto-retired. Does not query GCP, model or OpenAI.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "human_study" / "backend"))
from human_study.question_identity import question_family


def normalized(text):
    return " ".join(re.findall(r"\w+", (text or "").casefold()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Downloaded final.json")
    parser.add_argument("--show-wording", action="store_true",
                        help="print the complete displayed question wording")
    args = parser.parse_args()
    archive = json.loads(args.archive.read_text())
    questions = sorted(archive.get("questions", []), key=lambda q: q["ordinal"])
    adaptive = [q for q in questions if q.get("phase") == "intervention"]
    by_id, by_family, by_wording = defaultdict(list), defaultdict(list), defaultdict(list)
    for q in questions:
        if q["phase"] == "attention":
            continue
        by_id[q["target_variable"]].append(q["ordinal"])
        by_family[question_family(q["target_variable"])].append(
            (q["ordinal"], q["target_variable"])
        )
        by_wording[normalized(q.get("displayed_wording"))].append(
            (q["ordinal"], q["target_variable"])
        )
    print("SESSION:", archive.get("session_id"))
    print("Completed questions:", len(questions),
          "| adaptive:", len(adaptive),
          "| generation-abandoned:", len(archive.get("generation_abandoned_questions", [])))
    print("\nExact variable repeats:")
    for name, steps in sorted(by_id.items()):
        if len(steps) > 1:
            print(" ", name, "steps", steps)
    print("\nRepeated questionnaire families:")
    for name, rows in sorted(by_family.items()):
        if len(rows) > 1:
            print(" ", name, rows)
    print("\nIdentical displayed questions:")
    for name, rows in by_wording.items():
        if name and len(rows) > 1:
            print(" ", rows, ("wording=" + name[:240]) if args.show_wording else "")
    print("\nQuestion-generation failures and recoveries:")
    found = False
    for q in questions + archive.get("generation_abandoned_questions", []):
        if q.get("generation_failure_count") or q.get("last_generation_error"):
            found = True
            print(" ", q["ordinal"], q["target_variable"],
                  "status=", q["status"],
                  "count=", q.get("generation_failure_count"),
                  "error=", q.get("last_generation_error"),
                  "reason_codes=", q.get("last_generation_failure_codes", []))
        if args.show_wording and q.get("phase") == "intervention":
            print(" ", q["ordinal"], q["target_variable"], ":", q.get("displayed_wording", ""))
    if not found:
        print("  No persisted failed-generation attempt found in this final archive.")
    print("\nNOTE: Same broad subject does not necessarily mean same measured construct.")


if __name__ == "__main__":
    main()
