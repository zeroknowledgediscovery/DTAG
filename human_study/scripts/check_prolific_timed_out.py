#!/usr/bin/env python3
"""Read-only review of timed-out Prolific participants in the original DTAG study.

Looks up Prolific PIDs in Firestore, including unfinished sessions that have no
final.json or reward.json. Prints only counts and status, never question/answer text.
Does not modify Firestore, GCS, Prolific submissions, or payment status.

Usage:
  python human_study/scripts/check_prolific_timed_out.py PID1 PID2

Uses gcloud CLI credentials with Firestore HTTPS REST (no Python gRPC/ADC).
Pass --database explicitly if the Cloud Run lookup is unavailable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def configured_database(project: str, region: str, service: str) -> str:
    print("Checking Cloud Run Firestore database configuration...", file=sys.stderr, flush=True)
    try:
        output = subprocess.check_output(
            ["gcloud", "run", "services", "describe", service,
             "--project", project, "--region", region, "--format=json"],
            text=True, timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit("Cloud Run lookup timed out (20s); retry with --database dtag-human-pilot") from exc
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


def decode_value(value):
    """Decode Firestore REST values, without printing any respondent text."""
    if "mapValue" in value:
        return {k: decode_value(v) for k, v in
                (value["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in value:
        return [decode_value(v) for v in (value["arrayValue"].get("values") or [])]
    for key in ("stringValue", "timestampValue", "booleanValue",
                "integerValue", "doubleValue"):
        if key in value:
            return value[key]
    return None


def document_fields(doc):
    return {key: decode_value(value) for key, value in (doc.get("fields") or {}).items()}


def access_token():
    print("Acquiring gcloud CLI access token...", file=sys.stderr, flush=True)
    try:
        return subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True, stderr=subprocess.PIPE, timeout=15,
        ).strip()
    except subprocess.TimeoutExpired as exc:
        raise SystemExit("gcloud authentication timed out (15s)") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit("gcloud authentication failed: " + exc.stderr.strip()) from exc


def request_json(url, token, *, payload=None):
    """A bounded, read-only Firestore REST call; POST is only used for runQuery."""
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url, data=body,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"Firestore HTTP {exc.code}; check project, database and IAM roles") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"Firestore HTTPS connection failed: {exc}") from exc


def query_sessions(root_url, pid, token):
    payload = {
        "structuredQuery": {
            "from": [{"collectionId": "sessions"}],
            "where": {"fieldFilter": {
                "field": {"fieldPath": "prolific.prolific_pid"},
                "op": "EQUAL", "value": {"stringValue": pid}}},
            "select": {"fields": [{"fieldPath": name} for name in (
                "prolific.prolific_pid", "phase", "policy", "consent_accepted",
                "created_at", "pending_exports", "receipt", "completion_code")]},
            "limit": 10,
        }
    }
    data = request_json(root_url + ":runQuery", token, payload=payload)
    sessions = []
    for item in data:
        doc = item.get("document")
        if not doc:
            continue
        fields = document_fields(doc)
        if (fields.get("prolific") or {}).get("prolific_pid") == pid:
            sessions.append((doc["name"].rsplit("/", 1)[-1], fields))
    return sessions


def list_questions(root_url, session_id, token):
    url = root_url + "/sessions/" + quote(session_id, safe="") + "/questions"
    mask = ("status", "phase", "attention_passed", "response_timestamp")
    questions = []
    page_token = ""
    while True:
        params = [("pageSize", "100")] + [("mask.fieldPaths", field) for field in mask]
        if page_token:
            params.append(("pageToken", page_token))
        data = request_json(url + "?" + urlencode(params), token)
        questions.extend(document_fields(doc) for doc in data.get("documents", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return questions


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

    print("Connecting to Firestore HTTPS REST database:", database, file=sys.stderr, flush=True)
    token = access_token()
    root_url = ("https://firestore.googleapis.com/v1/projects/"
                + quote(args.project, safe="") + "/databases/"
                + quote(database, safe="()") + "/documents/studies/"
                + quote(args.study, safe=""))
    found = {}
    for pid in args.pids:
        print("Looking up participant:", pid[:6] + "…" + pid[-4:],
              file=sys.stderr, flush=True)
        found[pid] = query_sessions(root_url, pid, token)

    print("DTAG original-study read-only payment review", flush=True)
    print("project:", args.project, "database:", database, "study:", args.study)
    for pid in args.pids:
        print("\nParticipant:", pid[:6] + "…" + pid[-4:])
        sessions = found[pid]
        if not sessions:
            print("  no matching Firestore session (cannot infer participation from timeout alone)")
            continue
        for session_id, s in sessions:
            print("  Reading saved question counts...", flush=True)
            questions = list_questions(root_url, session_id, token)
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
            print("  session:", session_id)
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
