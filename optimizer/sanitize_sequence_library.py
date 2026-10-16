"""Non-destructive sanitation inventory for legacy DTAG question libraries.

Preserves every original CSV and validation output; reports what cannot be
combined with the new empty-centered coordinate and whether a published
sequence exists. Never reclassifies a legacy run as new experimental evidence.

    python -m optimizer.sanitize_sequence_library
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from .ideology_coordinates import COORDINATE


def digest_file(path):
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def inventory_legacy(legacy, output):
    legacy = Path(legacy).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    manifest = legacy / "library.json"
    records = json.loads(manifest.read_text()).get("attempts", []) if manifest.exists() else []
    rows, hashes = [], {}
    for record in records:
        location = record.get("sequence_file")
        sequence = Path(location) if location else None
        if sequence is not None and not sequence.is_absolute():
            sequence = legacy / sequence
        if sequence and not sequence.exists():
            # Historical files often stored their own absolute paths from another machine.
            portable = legacy / "sequences" / Path(location).name
            if portable.exists():
                sequence = portable
        exists = bool(sequence and sequence.is_file())
        file_sha = digest_file(sequence) if exists else None
        if file_sha:
            hashes.setdefault(file_sha, []).append(str(record.get("run_id")))
        meta = str(record.get("index_coordinate") or "legacy_uncentered_or_unknown")
        row = {
            "run_id": record.get("run_id"), "year": record.get("year"),
            "legacy_status": record.get("status"),
            "legacy_reported_label": record.get("observed_label"),
            "source_index_coordinate": meta,
            "source_file": str(sequence) if sequence else "",
            "sequence_exists": exists, "sequence_sha256": file_sha,
            "eligible_for_centered_catalog": False,
            "action": ("requires_fixed-sequence_new_centered_validation"
                       if exists else
                       "missing_sequence_or_incomplete_attempt"),
            "notes": ("Old experimental results must not be reclassified by "
                      "changing a label or copying the file; rerun the same "
                      "independently preselected set under the new coordinate.")
        }
        rows.append(row)
    for row in rows:
        if row["sequence_sha256"] and len(hashes[row["sequence_sha256"]]) > 1:
            row["duplicate_sequence_runs"] = ";".join(hashes[row["sequence_sha256"]])
        else:
            row["duplicate_sequence_runs"] = ""
    output.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "year", "legacy_status", "legacy_reported_label",
              "source_index_coordinate", "sequence_exists", "sequence_sha256",
              "duplicate_sequence_runs", "eligible_for_centered_catalog",
              "action", "source_file", "notes"]
    with (output / "legacy_inventory.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "legacy_root": str(legacy), "new_centered_root": str(output),
        "new_coordinate": COORDINATE, "n_prior_attempts": len(rows),
        "n_prior_files_found": sum(x["sequence_exists"] for x in rows),
        "n_unique_existing_sequences": len(hashes),
        "n_duplicate_file_groups": sum(len(v) > 1 for v in hashes.values()),
        "read_only": True,
        "policy": "Legacy attempts retained as historical; new centered runs use separate root.",
        "legacy_manifest_exists": manifest.exists()
    }
    (output / "legacy_inventory_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--legacy", default="outputs/optimizer/sequence_library")
    p.add_argument("--out", default="outputs/optimizer/sequence_library_empty_centered_v1")
    args = p.parse_args(argv)
    result = inventory_legacy(args.legacy, args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
