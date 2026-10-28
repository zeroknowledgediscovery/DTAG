#!/usr/bin/env python3
"""Read-only review of timed-out Prolific participants in the original DTAG study.

Looks up Prolific PIDs in Firestore, including unfinished sessions that have no
final.json or reward.json. Prints only counts and status, never question/answer text.
Does not modify Firestore, GCS, Prolific submissions, or payment status.

Usage:
  python human_study/scripts/check_prolific_timed_out.py PID1 PID2

Uses Google Application Default Credentials and Cloud Run's configured Firestore
database. Pass --database explicitly if the Cloud Run lookup is unavailable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import re
import subprocess


def configured_database(project: str, region: str, service: str) -> str:
    output = subprocess.check_output(
        ["gcloud", "run", "services", "describe", service,
         "--project", project, "--region", region, "--format=json"],
        text=True,
    )
    info = json.loads(output)
    template = info.get("spec", {}).get("template", {})
    containers = template.get("spec", {}).get("containers", []) or template.get("containers", [])
    if not containers:
        containers = info.get("template", {}).get("containers", [])
    for container in containers:
        for env in container.get("env", []):
            if env.get("name") == "DTAG_FIRESTORE_DATABASE":
                return env.get("value", "(default)")
    return "(default)"


def timestamp(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def printable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else "n/a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pids", nargs="+", help="Prolific participant IDs (not submission IDs)")
    parser.add_argument("--project", default="pkcsaas-01")
    parser.add_argument("--region", default="us-east1")
    parser.add_argument("--service", default="dtag-human-pilot")
    parser.add_argument("--database", help="Override Firestore database")
    parser.add_argument("--study", default="prolific-v3-human-opinions-2026-10")
    args = parser.parse_args()

    if any(not re.fullmatch(r"[a-zA-Z0-9]{6,48}", pid) for pid in args.pids):
        parser.error("participant IDs must be 6–48 letters/digits")
    if args.database:
        database = args.database
    else:
        database = configured_database(args.project, args.region, args.service)

    from google.cloud import firestore

    client = firestore.Client(project=args.project, database=database)
    root = client.collection("studies").document(args.study).collection("sessions")
    # The first paid study is small. Scan session headers only, avoiding any
    # composite-index requirement or disclosure of other participants' data.
    found = {pid: [] for pid in args.pids}
    for doc in root.stream():
        session = doc.to_dict() or {}
        pid = (session.get("prolific") or {}).get("prolific_pid")
        if pid in found:
            found[pid].append((doc, session))

    print("DTAG original-study read-only payment review")
    print("project:", args.project, "database:", database, "study:", args.study)
    for pid in args.pids:
        print("\nParticipant:", pid[:6] + "…" + pid[-4:])
        sessions = found[pid]
        if not sessions:
            print("  no matching Firestore session (cannot infer participation from timeout alone)")
            continue
        for doc, s in sessions:
            questions = [q.to_dict() or {} for q in doc.reference.collection("questions").stream()]
            answered = [q for q in questions if q.get("status") == "answered"]
            counts = Counter(q.get("phase", "unknown") for q in answered)
            checks = [q for q in answered if q.get("phase") == "attention"]
            passed = sum(q.get("attention_passed") is True for q in checks)
            times = [timestamp(q.get("response_timestamp")) for q in answered]
            times = [t for t in times if t is not None]
            last = max(times) if times else None
            created = timestamp(s.get("created_at"))
            duration = round((last - created).total_seconds() / 60, 1) if last and created else None
            pending = [q.get("phase") for q in questions if q.get("status") == "presented"]
            print("  session:", doc.id)
            print("  consent:", s.get("consent_accepted"), "phase:", s.get("phase"),
                  "policy:", s.get("policy"))
            print("  answered: baseline", counts["baseline"], "/6;",
                  "adaptive", counts["intervention"], "/20;",
                  "attention", counts["attention"], "/5")
            print("  attention passed:", passed, "/", len(checks))
            print("  created:", printable(s.get("created_at")))
            print("  latest recorded answer:", printable(last))
            print("  elapsed to last recorded answer (minutes):", printable(duration))
            print("  unfinished presented questions:", len(pending),
                  "pending archive exports:", len(s.get("pending_exports", [])))
            print("  completion receipt archived:", bool(s.get("receipt")),
                  "completion code issued:", bool(s.get("completion_code")))
            if (counts["baseline"] == 6 and counts["intervention"] == 20
                    and counts["attention"] == 5):
                print("  REVIEW: all 31 responses recorded; investigate why Prolific timed out")
            elif answered:
                print("  REVIEW: partial recorded participation; assess effort and any technical issue")
            else:
                print("  REVIEW: session opened but no answers recorded")


if __name__ == "__main__":
    main()
