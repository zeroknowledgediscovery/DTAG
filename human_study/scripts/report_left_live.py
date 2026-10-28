#!/usr/bin/env python3
"""Read-only interim directional report for the production fixed-left Prolific study.

Uses the active gcloud CLI login and Firestore HTTPS REST. Reads state indices
and minimal question metadata, never answer text or Prolific identifiers.
No scientific re-inference, database writes, Prolific API calls or payments.

Run: python3 -u human_study/scripts/report_left_live.py
Optional: --study prolific-v3-left-followup-staging-2026-10 --database dtag-human-pilot
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import statistics as stats
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def token():
    print("Authenticating with gcloud...", file=sys.stderr, flush=True)
    try:
        return subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True, stderr=subprocess.PIPE, timeout=20).strip()
    except subprocess.TimeoutExpired as exc:
        raise SystemExit("gcloud token command timed out; check CLI authentication") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit("gcloud authentication failed: " + exc.stderr.strip()) from exc


def get_json(url, access_token):
    req = Request(url, headers={"Authorization": "Bearer " + access_token})
    try:
        with urlopen(req, timeout=15) as res:
            return json.load(res)
    except HTTPError as exc:
        msg = exc.read(500).decode("utf-8", errors="replace")
        raise SystemExit(f"Firestore HTTP {exc.code}: {msg}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"Firestore HTTPS connection failed: {exc}") from exc


def decode(v):
    if "mapValue" in v:
        return {k: decode(z) for k, z in v["mapValue"].get("fields", {}).items()}
    if "arrayValue" in v:
        return [decode(z) for z in v["arrayValue"].get("values", [])]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    return None


def fields(document):
    return {k: decode(v) for k, v in document.get("fields", {}).items()}


def list_docs(url, access_token, mask):
    result, page_token = [], ""
    for page in range(1000):
        params = [("pageSize", "100")] + [("mask.fieldPaths", name) for name in mask]
        if page_token:
            params.append(("pageToken", page_token))
        response = get_json(url + "?" + urlencode(params), access_token)
        result.extend(response.get("documents", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return result
    raise SystemExit("Exceeded 1000 pages; refusing incomplete report")


def numeric(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def signed_counts(values):
    left = sum(d < -1e-10 for d in values)
    right = sum(d > 1e-10 for d in values)
    return f"{left} left / {right} right / {len(values)-left-right} unchanged"


def describe(values):
    if not values:
        return "no data"
    return (f"n={len(values)}  mean={stats.fmean(values):+.4f}  "
            f"median={stats.median(values):+.4f}  "
            f"{signed_counts(values)}")


def adaptive_count(s):
    # Each completed baseline/adaptive/attention answer increments next_step.
    # Attention checks do not contribute to the scientific index.
    return max(0, min(20, (s.get("next_step") or 0)
                       - (s.get("attention_completed") or 0) - 6))


def summarize(rows, trajectories):
    consented = [r for r in rows if r["consent"] is True]
    started = [r for r in consented if r["baseline"] is not None]
    adaptive = [r for r in started if r["adaptive_count"] > 0]
    complete = [r for r in started if r["adaptive_count"] == 20]
    finalized = [r for r in started if r["phase"] == "complete"]
    print("\nLEFT-ONLY PRODUCTION: INTERIM OBSERVED DIRECTION")
    print("sessions:", len(rows), "consented:", len(consented),
          "baseline established:", len(started),
          ">=1 adaptive:", len(adaptive),
          "20 adaptive:", len(complete), "finalized:", len(finalized))
    print("phase counts:", dict(sorted(Counter(r["phase"] for r in rows).items())))
    print("\nLatest available change from each participant's own baseline:")
    for label, subset in [
        ("All with >=1 adaptive", adaptive),
        ("Still partial (1-19)", [r for r in adaptive if r["adaptive_count"] < 20]),
        ("All 20 adaptive", complete),
        ("Finalized", finalized),
    ]:
        print(f"  {label}: {describe([r['delta'] for r in subset])}")
    print("\nBy progress at latest saved answer (not matched horizons):")
    for lo, hi in [(1, 4), (5, 9), (10, 14), (15, 19), (20, 20)]:
        group = [r["delta"] for r in adaptive if lo <= r["adaptive_count"] <= hi]
        print(f"  {lo:02d}-{hi:02d} adaptive: {describe(group)}")
    print("\nIndividual session directions (short opaque session IDs; no PIDs):")
    for r in sorted(started, key=lambda z: (z["adaptive_count"], z["sid"])):
        d = r["delta"]
        print(f"  {r['sid'][:8]}  {r['adaptive_count']:2d}/20 adaptive"
              f"  baseline={r['baseline']:+.4f}  now={r['current']:+.4f}"
              f"  delta={d:+.4f}  {r['phase']}")
    if trajectories:
        print("\nMatched adaptive-question horizons (only participants with that step):")
        for step in (1, 3, 5, 10, 15, 20):
            vals = [trace[step - 1] for trace in trajectories.values()
                    if (step - 1) in trace]
            print(f"  step {step:2d}: {describe(vals)}")
        print("\nIMPORTANT: Partial samples have varying follow-up lengths and are")
        print("not a randomized control comparison. Do not interpret a positive")
        print("mean before completion as proof the fixed-left intervention failed.")
    else:
        print("\nNo per-question trajectories requested (--trajectories for matched horizons).")
    print("Study indices reflect explicit accepted answer mappings, not forced")
    print("answers or hypothetical model responses. Negative delta means leftward.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project", default="pkcsaas-01")
    p.add_argument("--database", default="dtag-human-pilot")
    p.add_argument("--study", default="prolific-v3-left-followup-2026-10")
    p.add_argument("--no-trajectories", dest="trajectories", action="store_false",
                   help="fast session-header report without per-question trajectory reads")
    p.set_defaults(trajectories=True)
    args = p.parse_args()
    access_token = token()
    root = ("https://firestore.googleapis.com/v1/projects/"
            + quote(args.project, safe="") + "/databases/"
            + quote(args.database, safe="()")
            + "/documents/studies/" + quote(args.study, safe="") + "/sessions")
    mask = ("consent_accepted", "phase", "policy", "next_step", "attention_completed",
            "state.baseline_index", "state.current_index", "created_at", "updated_at")
    print("Fetching session indices from", args.study, file=sys.stderr, flush=True)
    docs = list_docs(root, access_token, mask)
    rows = []
    trajectories = {}
    for doc in docs:
        s = fields(doc)
        if s.get("consent_accepted") is not True:
            rows.append({"sid": doc["name"].rsplit("/", 1)[-1],
                         "consent": s.get("consent_accepted"),
                         "phase": s.get("phase", "unknown"),
                         "baseline": None, "current": None,
                         "delta": None, "adaptive_count": 0})
            continue
        if s.get("policy") not in (None, "left"):
            raise SystemExit("Unexpected policy in fixed-left study: " + str(s["policy"]))
        state = s.get("state") or {}
        baseline = numeric(state.get("baseline_index"))
        current = numeric(state.get("current_index"))
        sid = doc["name"].rsplit("/", 1)[-1]
        n = adaptive_count(s) if baseline is not None else 0
        rows.append({"sid": sid, "consent": True,
                     "phase": s.get("phase", "unknown"),
                     "baseline": baseline, "current": current,
                     "delta": current - baseline if baseline is not None and current is not None else None,
                     "adaptive_count": n})
        if args.trajectories and baseline is not None:
            print("Reading adaptive trajectory for", sid[:8],
                  file=sys.stderr, flush=True)
            qurl = root + "/" + quote(sid, safe="") + "/questions"
            qdocs = list_docs(qurl, access_token,
                              ("status", "phase", "step", "ordinal",
                               "index_result.index_after"))
            values = {}
            for qdoc in qdocs:
                q = fields(qdoc)
                if q.get("phase") == "intervention" and q.get("status") == "answered":
                    val = numeric((q.get("index_result") or {}).get("index_after"))
                    if val is not None:
                        step = q.get("step")
                        if isinstance(step, int) and 0 <= step < 20:
                            values[step] = val - baseline
            if len(values) != n:
                print(f"WARNING: {sid[:8]} progress={n}, trajectory records={len(values)}",
                      file=sys.stderr, flush=True)
            trajectories[sid] = values
    print("Fetched", len(rows), "session headers.", file=sys.stderr, flush=True)
    summarize(rows, trajectories)


if __name__ == "__main__":
    main()
