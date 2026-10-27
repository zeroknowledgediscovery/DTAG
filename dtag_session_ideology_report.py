#!/usr/bin/env python3
"""Read-only report of DTAG study sessions archived in Google Cloud Storage.

Uses the active gcloud CLI login (no Python Google Cloud SDK dependency).
Does not change any GCS objects, participant sessions, or cloud resources.

Examples:
  python3 dtag_session_ideology_report.py
  python3 dtag_session_ideology_report.py --details --csv dtag_sessions.csv
  python3 dtag_session_ideology_report.py --study prolific-v3-human-opinions-2026-10
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_BUCKET = "pkcsaas-01-dtag-study-data"
SESSION_RE = re.compile(r"^gs://[^/]+/studies/([^/]+)/sessions/([^/]+)/(.+)$")
ANSWERED_INTERVENTION_RE = re.compile(r"^questions/[a-fA-F0-9]{32}\.json$")


def gs(*args: str) -> str:
    try:
        return subprocess.check_output(["gcloud", "storage", *args], text=True,
                                       stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("gcloud CLI not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or "gcloud storage command failed").strip()) from exc


def fetch_json(uri: str) -> dict:
    try:
        data = json.loads(gs("cat", uri))
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Invalid JSON at {uri}: {exc}") from exc


def number(value):
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def display(value):
    return f"{value:+.5f}" if value is not None else "—"


def summarize(study: str, sid: str, objects: dict[str, str]):
    """Use immutable final.json if present, otherwise assignment + answered items."""
    final = None
    if "final.json" in objects:
        final = fetch_json(objects["final.json"])
        status = "COMPLETE"
        arm = final.get("policy") or (final.get("reward") or {}).get("policy")
        baseline = number(final.get("baseline_index"))
        final_index = number(final.get("final_index"))
        questions = final.get("questions") or []
        interventions = [q for q in questions if q.get("phase") == "intervention"
                         and isinstance(q.get("index_result"), dict)]
    else:
        assignment = (fetch_json(objects["events/assignment.json"])
                      if "events/assignment.json" in objects else {})
        arm = assignment.get("policy")
        baseline = number(assignment.get("baseline_index"))
        final_index = None
        interventions = []
        for key, uri in objects.items():
            if ANSWERED_INTERVENTION_RE.fullmatch(key):
                payload = fetch_json(uri)
                question = payload.get("question") or {}
                if question.get("phase") == "intervention" and isinstance(question.get("index_result"), dict):
                    interventions.append(question)
        status = "IN_PROGRESS" if arm is not None else "NOT_RANDOMIZED"

    trajectory = []
    for q in interventions:
        after = number(q["index_result"].get("index_after"))
        if after is None:
            continue
        step = q.get("step")
        ordinal = q.get("ordinal")
        trajectory.append({"step": step if isinstance(step, int) else None,
                           "ordinal": ordinal if isinstance(ordinal, int) else None,
                           "index": after, "delta": after - baseline if baseline is not None else None})
    trajectory.sort(key=lambda r: (r["ordinal"] if r["ordinal"] is not None else 999999,
                                  r["step"] if r["step"] is not None else 999999))
    # For incomplete sessions, the most recent answered intervention item is the latest
    # ideology measurement. If no adaptive answer exists, it equals baseline.
    if final is None:
        latest = trajectory[-1]["index"] if trajectory else baseline
    else:
        latest = final_index if final_index is not None else (trajectory[-1]["index"] if trajectory else baseline)

    result = {"study_id": study, "session_id": sid, "status": status,
              "arm": arm or "—", "baseline_ideology": baseline,
              "latest_ideology": latest,
              "change_from_baseline": latest - baseline if baseline is not None and latest is not None else None,
              "adaptive_answers": len(trajectory), "trajectory": trajectory}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bucket", default=DEFAULT_BUCKET, help="Existing GCS research bucket")
    ap.add_argument("--study", help="Optional study ID filter (default: all studies)")
    ap.add_argument("--details", action="store_true", help="Print each adaptive ideology relative to baseline")
    ap.add_argument("--csv", metavar="FILE", help="Also write one-row-per-session CSV")
    args = ap.parse_args()
    if args.study and not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", args.study):
        ap.error("invalid --study value")

    prefix = f"gs://{args.bucket}/studies/"
    try:
        listings = gs("ls", "--recursive", prefix).splitlines()
    except RuntimeError as exc:
        print(f"Could not list GCS study archive: {exc}", file=sys.stderr)
        return 1
    grouped = defaultdict(dict)
    for uri in listings:
        match = SESSION_RE.fullmatch(uri.strip())
        if not match:
            continue
        study, sid, name = match.groups()
        if args.study and study != args.study:
            continue
        grouped[(study, sid)][name] = uri.strip()

    print(f"Bucket: gs://{args.bucket} | archived sessions: {len(grouped)}")
    print("Arm assignment occurs after six baseline answers; not-yet-randomized sessions have no ideology index.\n")
    print(f"{'STUDY':39} {'SESSION':32} {'STATUS':14} {'ARM':8} {'N':>3} {'BASELINE':>11} {'LATEST':>11} {'DELTA':>11}")
    print("-" * 145)
    rows = []
    for (study, sid), objects in sorted(grouped.items()):
        try:
            rec = summarize(study, sid, objects)
        except RuntimeError as exc:
            print(f"WARNING: could not read {study}/{sid}: {exc}", file=sys.stderr)
            continue
        rows.append(rec)
        print(f"{study[:39]:39} {sid[:32]:32} {rec['status']:14} {rec['arm'][:8]:8} "
              f"{rec['adaptive_answers']:3d} {display(rec['baseline_ideology']):>11} "
              f"{display(rec['latest_ideology']):>11} {display(rec['change_from_baseline']):>11}")
        if args.details:
            for step in rec["trajectory"]:
                step_no = step["step"] + 1 if step["step"] is not None else "?"
                print(f"    Adaptive Q{step_no}: ideology={display(step['index'])}  "
                      f"Δ from baseline={display(step['delta'])}")

    if args.csv:
        fields = ["study_id", "session_id", "status", "arm", "adaptive_answers",
                  "baseline_ideology", "latest_ideology", "change_from_baseline"]
        with Path(args.csv).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({field: row[field] for field in fields} for row in rows)
        print(f"\nSaved CSV: {args.csv}")
    print(f"\nReported {len(rows)} sessions. Δ = latest ideology − baseline ideology.")
    print("GCS-only: sessions with no archived objects (Firestore-only) are not included.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
