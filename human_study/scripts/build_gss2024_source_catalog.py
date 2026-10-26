#!/usr/bin/env python3
"""Create immutable, local prompt evidence from a model-backed GSS R2 audit.

Input is produced by audit_all_native_gss_2024.py --codebook, which uses
the 2024 native model's source-map variables and the official 2024 R2 PDF.
The output includes only variable entry labels and interviewer notes,
NOT frequency tables or raw respondent data. This is documentary evidence,
not a statement that questionnaire routing/scale has been certified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

R2_CODEBOOK = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/"
    "codebook/GSS%202024%20Codebook%20R2.pdf"
)
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "data" /
    "gss_2024_r2_source_context.json"
)

# This is the codebook's column/table header, not a respondent instruction.
TABLE = re.compile(
    r"(?m)^\s*(?:PCT Excl\.|LABEL VALUE COUNT|RESERVED CODES:|SUBTOTALS:)"
)


def build(full_audit):
    summary = full_audit.get("summary", {})
    if (summary.get("model_key") != "gss/gss_2024"
            or summary.get("total_native_model_variables") != 811
            or not summary.get("all_native_variables_enumerated")
            or summary.get("semantic_map_matched") != 811):
        raise ValueError("source catalog requires actual 811-variable native model audit")
    entries = full_audit.get("variables", [])
    if len(entries) != 811:
        raise ValueError("audit inventory incomplete")
    result = {}
    for row in entries:
        v = row["variable"].casefold()
        original = row.get("codebook_entry_text") or ""
        if not original:
            continue
        parts = TABLE.split(original, maxsplit=1)
        label = parts[0].strip()
        if not label.startswith("Variable: "):
            raise ValueError(f"unexpected documentation for {v}")
        if len(label) > 6000:
            raise ValueError(f"source excerpt exceeds prompt context budget: {v}")
        result[v] = {
            "excerpt": label,
            "pdf_pages": row.get("codebook_pdf_pages") or [],
        }
    if len(result) < 750:
        raise ValueError(f"too few codebook entries: {len(result)}")
    return {
        "schema_version": "1",
        "model_key": "gss/gss_2024",
        "documentation": "official_GSS_2024_R2_codebook_label_and_notes_unverified_routing",
        "source_url": R2_CODEBOOK,
        "source_audit_sha256": hashlib.sha256(
            json.dumps(summary, sort_keys=True).encode()
        ).hexdigest(),
        "matched_entries": len(result),
        "variables": dict(sorted(result.items())),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audit_json", type=Path)
    p.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    a = p.parse_args()
    result = build(json.loads(a.audit_json.read_text(encoding="utf-8")))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{result['matched_entries']} original codebook labels archived to {a.out}")


if __name__ == "__main__":
    main()
