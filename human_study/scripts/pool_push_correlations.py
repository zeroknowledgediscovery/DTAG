#!/usr/bin/env python3
"""Pool original and later DTAG left/right push cohorts; correlate baseline vs endpoint.

Read-only: the only cloud actions are gcloud storage ls/cat. Only complete
20-adaptive-question sessions contribute; partial sessions are excluded from
endpoint correlations. Original left and later fixed-left are pooled into ONE
left group. Original right is ONE right group (optional further right CSV).

Run from the repository root:
    python3 -u human_study/scripts/pool_push_correlations.py

Supply prior local CSVs to avoid re-reading their GCS archives:
    python3 -u human_study/scripts/pool_push_correlations.py \
      --original-csv original_sessions.csv --left-csv left_sessions.csv
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
from pathlib import Path
import statistics as stat
import subprocess
import sys


STUDY_ORIGINAL = "prolific-v3-human-opinions-2026-10"
STUDY_LEFT = "prolific-v3-left-followup-2026-10"
BUCKET = "pkcsaas-01-dtag-study-data"


def gcloud(*args, timeout=60):
    try:
        p = subprocess.run(["gcloud", "storage", *args], check=True, timeout=timeout,
                           text=True, capture_output=True)
        return p.stdout
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"gcloud storage {args[0]} timed out ({timeout}s)") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"gcloud storage {args[0]} failed: {exc.stderr.strip()}") from exc


def number(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def read_csv(path, allowed_arms):
    rows = []
    for row in csv.DictReader(Path(path).open(newline="", encoding="utf-8")):
        if row.get("status") != "COMPLETE" or int(row.get("adaptive_answers") or 0) != 20:
            continue
        arm = row.get("arm")
        if arm not in allowed_arms:
            continue
        x, y = number(row.get("baseline_ideology")), number(row.get("latest_ideology"))
        if x is not None and y is not None:
            rows.append((row["study_id"], row["session_id"], arm, x, y))
    return rows


def archive_rows(study_id, bucket):
    import json
    prefix = f"gs://{bucket}/studies/{study_id}/sessions/"
    print(f"Discovering archived completed sessions: {study_id}", file=sys.stderr, flush=True)
    listed = gcloud("ls", "--recursive", prefix, timeout=60).splitlines()
    finals = sorted(p.strip() for p in listed if p.strip().endswith("/final.json"))
    print(f"  {len(finals)} final records found", file=sys.stderr, flush=True)

    def read_one(uri):
        # Immutable final archive is authoritative for baseline and endpoint.
        final = json.loads(gcloud("cat", uri, timeout=35))
        x, y = number(final.get("baseline_index")), number(final.get("final_index"))
        if x is None or y is None:
            return None
        qs = final.get("questions") or []
        n_adaptive = sum(q.get("phase") == "intervention" for q in qs)
        if n_adaptive != 20:
            return None
        return (study_id, final.get("session_id") or uri.split("/sessions/")[1].split("/")[0],
                final.get("policy"), x, y)

    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(read_one, uri): uri for uri in finals}
        for i, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            if row is not None:
                rows.append(row)
            if i % 10 == 0 or i == len(finals):
                print(f"  read {i}/{len(finals)} records", file=sys.stderr, flush=True)
    return rows


def summarize(name, rows):
    pairs = [(x, y) for _, _, _, x, y in rows]
    n = len(pairs)
    print(f"\\n{name}: {n} complete participants")
    if not n:
        return
    x = [a for a, b in pairs]
    y = [b for a, b in pairs]
    d = [b - a for a, b in pairs]
    print(f"  baseline mean {stat.fmean(x):+.5f}; final mean {stat.fmean(y):+.5f}")
    print(f"  mean displacement {stat.fmean(d):+.5f}; "
          f"median {stat.median(d):+.5f}")
    print(f"  endpoint direction: {sum(v < -1e-10 for v in d)} left / "
          f"{sum(v > 1e-10 for v in d)} right / "
          f"{sum(abs(v) <= 1e-10 for v in d)} unchanged")
    print(f"  baseline: {sum(v < 0 for v in x)} negative / {sum(v >= 0 for v in x)} nonnegative")

    for label, z in [
        ("initial vs final", y),
        ("initial vs displacement", d),
    ]:
        if n < 3 or len(set(x)) < 2 or len(set(z)) < 2:
            print(f"  Pearson ({label}): insufficient variation or n<3")
            continue
        r = stat.correlation(x, z)
        ci = ""
        if n > 3 and abs(r) < 1:
            z0 = math.atanh(r)
            half = 1.959963984540054 / math.sqrt(n - 3)
            ci = f"; Fisher 95% CI [{math.tanh(z0-half):+.4f}, {math.tanh(z0+half):+.4f}]"
        p = ""
        try:
            from scipy.stats import pearsonr
            p = f"; two-sided p={pearsonr(x, z).pvalue:.4g}"
        except ImportError:
            p = "; p-value unavailable (scipy not installed)"
        print(f"  Pearson ({label}): r={r:+.4f}{ci}{p}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default=BUCKET)
    p.add_argument("--original-csv", help="Use original four-arm exported session CSV")
    p.add_argument("--left-csv", help="Use left follow-up exported session CSV")
    p.add_argument("--right-csv", help="Optional *paid* right-only follow-up CSV")
    args = p.parse_args()

    original = (read_csv(args.original_csv, {"left", "right"})
                if args.original_csv else archive_rows(STUDY_ORIGINAL, args.bucket))
    new_left = (read_csv(args.left_csv, {"left"})
                if args.left_csv else archive_rows(STUDY_LEFT, args.bucket))
    extra_right = read_csv(args.right_csv, {"right"}) if args.right_csv else []

    # Exclude duplicate session records, never count a person twice in a study.
    unique = {}
    for row in original + new_left + extra_right:
        if row[2] in ("left", "right"):
            key = (row[0], row[1])
            if key in unique and unique[key] != row:
                raise SystemExit("Conflicting duplicate session: " + str(key))
            unique[key] = row
    all_rows = list(unique.values())
    by_arm = {arm: [r for r in all_rows if r[2] == arm] for arm in ("left", "right")}

    print("\\nPooled DTAG human endpoints: original + left follow-up, no separate left cohorts")
    print("Completed 20-adaptive-answer sessions only; no partial-index imputation.")
    summarize("ALL LEFT PUSH (pooled)", by_arm["left"])
    summarize("ALL RIGHT PUSH", by_arm["right"])
    print("\\nInterpretation: baseline→final correlation measures preservation of")
    print("participant ordering; baseline→displacement correlation tests whether")
    print("the direction or magnitude of movement depends on starting ideology.")
    print("Cross-cohort pooled endpoints are descriptive, not jointly randomized.")


if __name__ == "__main__":
    main()
