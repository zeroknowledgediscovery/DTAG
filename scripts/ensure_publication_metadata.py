#!/usr/bin/env python3
"""Generate pdfLaTeX plot metadata from existing DTAG figure CSVs.

No simulation, replay, or question-index optimization is performed.
"""
import argparse
import csv
import io
import json
from pathlib import Path

PERSONAS = (
    "cm_rural_alabama", "wf_new_york_city",
    "religious_conservative_woman_texas", "secular_liberal_man_seattle",
    "hispanic_catholic_man_arizona", "black_churchgoing_woman_atlanta",
)

def records(path):
    if not path.is_file():
        raise FileNotFoundError(f"Missing required figure CSV: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        yield from csv.DictReader(stream)

def ci_extent(path):
    values = []
    for row in records(path):
        mean = float(row["mean"])
        values.extend((abs(mean-float(row["minus"])), abs(mean+float(row["plus"]))))
    if not values:
        raise ValueError(f"Empty figure CSV: {path}")
    return max(values)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("figures", type=Path)
    args = ap.parse_args()
    directory = args.figures.resolve(strict=True)
    with (directory/"optimization_report.json").open(encoding="utf-8") as fh:
        report = json.load(fh)
    endpoint_bound = trajectory_bound = order_bound = 0.0
    for policy in ("right", "left", "neutral", "random"):
        endpoint_bound = max(endpoint_bound, ci_extent(directory/f"pub_endpoint_{policy}.csv"))
        for person in PERSONAS:
            for row in records(directory/f"pub_trajectory_{person}_{policy}.csv"):
                trajectory_bound = max(trajectory_bound, abs(float(row["lo"])), abs(float(row["hi"])))
    for policy in ("right", "left", "neutral"):
        for person in PERSONAS:
            order_bound = max(order_bound, ci_extent(directory/f"pub_order_{person}_{policy}.csv"))
            if not (directory/f"heatmap_{person}_{policy}.csv").is_file():
                raise FileNotFoundError(f"Missing heatmap CSV: heatmap_{person}_{policy}.csv")
    data = {
        "steps": int(report["steps"]),
        "reps": int(report["reps"]),
        "displayed_questions": int(report["displayed_questions"]),
        "total_questions": int(report["total_questions"]),
        "endpoint_bound": f"{max(endpoint_bound*1.16,.02):.4f}",
        "trajectory_bound": f"{max(trajectory_bound*1.16,.02):.4f}",
        "order_bound": f"{max(order_bound*1.16,.01):.4f}",
    }
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=data.keys())
    writer.writeheader()
    writer.writerow(data)
    new_bytes = buffer.getvalue().encode("utf-8")
    target = directory/"publication_metadata.csv"
    if not target.is_file() or target.read_bytes() != new_bytes:
        target.write_bytes(new_bytes)
        print(f"Generated {target}")
    else:
        print(f"Plot metadata up to date: {target}")
    print(f"steps={data['steps']} reps={data['reps']} active_question_ids={data['displayed_questions']}")

if __name__ == "__main__":
    main()
