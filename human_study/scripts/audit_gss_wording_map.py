#!/usr/bin/env python3
"""Read-only audit of GSS 2024 semantic-map sources needing stand-alone context.

No GSS responses, model downloads, LLM calls or external services.
A source flag indicates an item to examine, not automatically a defect.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from human_study.study_config import StudyConfig
from human_study.wording_contracts import CONTRACTS, validates_standalone, validates_wording

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "maps/gss/gss_2024_map.csv"
UNVERIFIED_EXCLUDED = frozenset(
    {"racdif1x", "racdif2x", "racdif3x", "racdif4x", "racdif5x"}
)
CONFIGS = [
    ROOT / "human_study/config/study.prolific.example.yaml",
    ROOT / "human_study/config/study.prolific.gcptest.yaml",
]
# Signals from the actual map, not a claim that all flagged entries are
# ill-formed. Some are demographic or conditional and already non-askable.
SUSPECT_SOURCE = re.compile(
    r"(?:\.{3,}|…|\b(?:such|this) a? ?person\b|"
    r"^\s*if (?:she|he)\b|"
    r"^\s*(?:should|suppose) (?:he|she|it)\b|"
    r"\{#[a-z]+\}|"
    r"\(\s*(?:please tell me|do you think|would you|now consider|"
    r"on the average|for each|i am going to name))",
    re.IGNORECASE,
)


def inspect():
    with MAP.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        item = row["variable"].casefold()
        original = (row.get("question_text_filled") or
                    row.get("question_text") or "").strip()
        contract = CONTRACTS.get(item)
        yield {
            "variable": item,
            "source_flagged": bool(SUSPECT_SOURCE.search(original)),
            "contracted": contract is not None,
            "unverified_excluded": item in UNVERIFIED_EXCLUDED,
            "contract_source_valid": (
                validates_standalone(contract.source)
                and validates_wording(item, contract.source)
            ) if contract else None,
            "original_map_excerpt": original[:320],
        }


def validate(rows):
    lookup = {r["variable"]: r for r in rows}
    issues = []
    for item in ("colmslm", "colath", "colrac", "colcom", "libmslm",
                 "libcom", "abnomore", "abrape", "suicide1", "eqwlth"):
        row = lookup.get(item)
        if not row or not row["contracted"] or not row["contract_source_valid"]:
            issues.append(f"required standalone source contract missing: {item}")
    for item, row in lookup.items():
        if row["contracted"] and not row["contract_source_valid"]:
            issues.append(f"source contract fails its own validator: {item}")
    for config_path in CONFIGS:
        cfg = StudyConfig.load(config_path)
        absent = sorted(UNVERIFIED_EXCLUDED - set(cfg.excluded_ids))
        if absent:
            issues.append(f"{config_path}: unresolved source items not excluded: {absent}")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="optional JSON report path")
    parser.add_argument("--check", action="store_true", help="fail on violated source audit invariants")
    args = parser.parse_args()
    rows = list(inspect())
    issues = validate(rows)
    reported = [r for r in rows if r["source_flagged"]]
    residual = [r for r in reported if not (r["contracted"] or r["unverified_excluded"])]
    print("Native GSS 2024 map entries:", len(rows))
    print("Potentially context-dependent source labels:", len(reported))
    print("Source-grounded contracts:", sum(r["contracted"] for r in rows))
    print("Flagged without source-grounded contract:", len(residual))
    print("Explicitly excluded unverified wording variants:", sorted(UNVERIFIED_EXCLUDED))
    print("Remaining flagged map entries require investigator classification, "
          "including non-opinion/demographic and conditional items.")
    print("Uncontracted example IDs:", [r["variable"] for r in residual[:30]])
    for issue in issues:
        print("FAIL:", issue)
    if args.out:
        Path(args.out).write_text(json.dumps({
            "schema_version": "1", "total_map_items": len(rows),
            "source_flagged": len(reported), "contracted": sum(r["contracted"] for r in rows),
            "unresolved_source_flags": residual, "issues": issues,
        }, indent=2))
    if args.check and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
