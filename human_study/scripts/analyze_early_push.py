#!/usr/bin/env python3
"""Do the first 1-5 adaptive answers predict later Right-push movement?

Read-only Firestore analysis, using saved question-level LSM indices (no inference).
Analyzes two distinct cohorts without pooling their incompatible initial states:
  (1) calibrated, initially-left participants assigned to Right push
  (2) Democrat-recruited, zero-calibration participants assigned to Right push

Only sessions with all 20 adaptive answers are included in the main analysis.
No respondent text, Prolific PIDs, session IDs, or individual trajectories are
printed or written. If --out is supplied, only aggregate CSVs are written.

Usage:
  python -u human_study/scripts/analyze_early_push.py
  python -u human_study/scripts/analyze_early_push.py --out /tmp/dtag-early-push
  python -u human_study/scripts/analyze_early_push.py --democrat-campaign-id ID
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from math import comb, isfinite
from pathlib import Path
from statistics import fmean, median
from urllib.parse import quote

from report_left_live import token, list_docs, fields, numeric

CALIBRATED_STUDIES = (
    "prolific-v3-human-opinions-2026-10",
    "prolific-v3-right-followup-2026-10",
)
NOCAL_STUDY = "dtag-v3-nocal-right-2026-10"
DEFAULT_DEMOCRAT_CAMPAIGN = "6ae37b8688d760488b8df1b0"
EPS = 1e-10
STEPS = 20


def average(values):
    return fmean(values) if values else float("nan")


def percent(num, den):
    return f"{100*num/den:.1f}%" if den else "n/a"


def formatted(value):
    return f"{value:+.5f}" if isfinite(value) else "n/a"


def fisher_two_sided(a, b, c, d):
    """Exact two-sided Fisher probability for 2x2 counts; no SciPy needed."""
    n = a + b + c + d
    if n == 0:
        return float("nan")
    r, col = a + b, a + c
    lo, hi = max(0, r - (n - col)), min(r, col)
    denom = comb(n, r)

    def probability(x):
        return comb(col, x) * comb(n - col, r - x) / denom

    observed = probability(a)
    return sum(probability(x) for x in range(lo, hi + 1)
               if probability(x) <= observed + 1e-12)


def root_url(project, database, study):
    return ("https://firestore.googleapis.com/v1/projects/"
            + quote(project, safe="") + "/databases/" + quote(database, safe="()")
            + "/documents/studies/" + quote(study, safe="") + "/sessions")


def read_cohort(project, database, studies, credential, *, calibrated, campaign):
    kept, totals = [], Counter()
    for study in studies:
        root = root_url(project, database, study)
        headers = list_docs(root, credential, (
            "consent_accepted", "policy", "next_step", "attention_completed",
            "state.baseline_index", "state.current_index",
            "prolific.prolific_study_id", "phase",
        ))
        totals["sessions_found"] += len(headers)
        for doc in headers:
            s = fields(doc)
            if s.get("consent_accepted") is not True or s.get("policy") != "right":
                continue
            if campaign is not None and (
                (s.get("prolific") or {}).get("prolific_study_id") != campaign
            ):
                continue
            initial = numeric((s.get("state") or {}).get("baseline_index"))
            current = numeric((s.get("state") or {}).get("current_index"))
            if initial is None or current is None:
                continue
            if calibrated and not initial < -EPS:
                continue
            totals["eligible_right_push"] += 1
            substantive = int(s.get("next_step") or 0) - int(s.get("attention_completed") or 0)
            adaptive = substantive - (6 if calibrated else 0)
            if adaptive < STEPS:
                totals["still_partial"] += 1
                continue
            if adaptive != STEPS:
                totals["unexpected_answer_count"] += 1
                continue
            sid = doc["name"].rsplit("/", 1)[-1]
            qdocs = list_docs(root + "/" + quote(sid, safe="") + "/questions",
                              credential, (
                                  "phase", "status", "step",
                                  "index_result.index_after",
                                  "index_result.index_before",
                                  "index_result.predicted_model_delta",
                                  "index_result.observed_conditional_index_delta",
                              ))
            after, prediction, observed = {}, {}, {}
            bad = False
            for qdoc in qdocs:
                q = fields(qdoc)
                if q.get("phase") != "intervention" or q.get("status") != "answered":
                    continue
                step = q.get("step")
                ir = q.get("index_result") or {}
                value = numeric(ir.get("index_after"))
                pred = numeric(ir.get("predicted_model_delta"))
                actual = numeric(ir.get("observed_conditional_index_delta"))
                if not isinstance(step, int) or step < 0 or step >= STEPS or value is None:
                    bad = True
                    continue
                if step in after:
                    bad = True
                    continue
                after[step] = value
                prediction[step] = pred
                observed[step] = actual
            if bad or set(after) != set(range(STEPS)):
                totals["missing_or_duplicate_trajectory"] += 1
                continue
            trajectory = [initial] + [after[i] for i in range(STEPS)]
            if abs(trajectory[-1] - current) > 1e-7:
                totals["inconsistent_final_index"] += 1
                continue
            kept.append({"trajectory": trajectory, "prediction": prediction,
                         "observed": observed, "study": study})
    return kept, totals


def analyze(cohort, label):
    rows, trends = [], []
    n = len(cohort)
    print(f"\n=== {label} ===")
    print(f"Complete trajectories: {n}")
    if not n:
        return rows, trends
    overall = [s["trajectory"][STEPS] - s["trajectory"][0] for s in cohort]
    n_right = sum(d > EPS for d in overall)
    print(f"Overall Right-push success: {n_right}/{n} ({percent(n_right, n)})"
          f" | mean Δ={formatted(average(overall))}")
    print("\nEarly movement direction -> later movement during remaining questions")
    print("k  early group        n   later right    mean later Δ   final right   mean final Δ")
    for k in range(1, 6):
        subsets = {
            "early right": [s for s in cohort if s["trajectory"][k] - s["trajectory"][0] > EPS],
            "early left/flat": [s for s in cohort if s["trajectory"][k] - s["trajectory"][0] <= EPS],
        }
        for group, members in subsets.items():
            later = [s["trajectory"][STEPS] - s["trajectory"][k] for s in members]
            final = [s["trajectory"][STEPS] - s["trajectory"][0] for s in members]
            early = [s["trajectory"][k] - s["trajectory"][0] for s in members]
            lr = sum(x > EPS for x in later)
            fr = sum(x > EPS for x in final)
            rows.append({
                "cohort": label, "k": k, "early_group": group, "n": len(members),
                "mean_early_delta": average(early),
                "mean_later_delta": average(later),
                "later_right_count": lr, "later_right_fraction": lr / len(members) if members else "",
                "mean_final_delta": average(final),
                "final_right_count": fr, "final_right_fraction": fr / len(members) if members else "",
            })
            print(f"{k}  {group:16s} {len(members):2d}   "
                  f"{lr:2d}/{len(members):2d} ({percent(lr, len(members)):>5s})"
                  f"   {formatted(average(later)):>11s}   "
                  f"{fr:2d}/{len(members):2d} ({percent(fr, len(members)):>5s})"
                  f"   {formatted(average(final)):>11s}")
        pos, neg = subsets["early right"], subsets["early left/flat"]
        a = sum(s["trajectory"][-1] - s["trajectory"][k] > EPS for s in pos)
        b = len(pos) - a
        c = sum(s["trajectory"][-1] - s["trajectory"][k] > EPS for s in neg)
        d = len(neg) - c
        p = fisher_two_sided(a, b, c, d)
        print(f"   Fisher exact (early direction vs SUBSEQUENT right movement): p={p:.4f}")
    print("\nMatched question horizons (same completed participants):")
    print("step   mean Δ from start   fraction right   mean step Δ   mean model-predicted Δ")
    for k in range(STEPS + 1):
        deltas = [s["trajectory"][k] - s["trajectory"][0] for s in cohort]
        actual = ([s["trajectory"][k] - s["trajectory"][k-1] for s in cohort]
                  if k else [])
        predicted = ([s["prediction"][k-1] for s in cohort
                      if s["prediction"].get(k-1) is not None] if k else [])
        nr = sum(d > EPS for d in deltas)
        trends.append({
            "cohort": label, "step": k, "n": n,
            "mean_delta_from_start": average(deltas), "median_delta_from_start": median(deltas),
            "right_count": nr, "right_fraction": nr / n,
            "mean_actual_step_delta": average(actual),
            "mean_predicted_target_delta": average(predicted),
        })
        if k in (0, 1, 2, 3, 4, 5, 10, 15, 20):
            print(f"{k:>4}    {formatted(average(deltas)):>10s}       "
                  f"{percent(nr, n):>6s}       {formatted(average(actual)):>10s}"
                  f"     {formatted(average(predicted)):>10s}")
    return rows, trends


def write_aggregate_csv(outdir, name, rows):
    if not rows:
        return
    with (outdir / name).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="pkcsaas-01")
    parser.add_argument("--database", default="dtag-human-pilot")
    parser.add_argument("--democrat-campaign-id", default=DEFAULT_DEMOCRAT_CAMPAIGN)
    parser.add_argument("--calibrated-study", action="append", dest="calibrated_studies",
                        help="Override calibrated study IDs (repeat for multiple studies)")
    parser.add_argument("--out", type=Path, help="Optional private output directory for AGGREGATES ONLY")
    args = parser.parse_args()
    credential = token()
    reports = []
    trends = []
    populations = [
        ("Calibrated: initially left, Right push",
         args.calibrated_studies or CALIBRATED_STUDIES, True, None),
        ("Democrats: no calibration, Right push",
         (NOCAL_STUDY,), False, args.democrat_campaign_id),
    ]
    for label, studies, calibrated, campaign in populations:
        subjects, counts = read_cohort(
            args.project, args.database, studies, credential,
            calibrated=calibrated, campaign=campaign,
        )
        print("\nSources:", ", ".join(studies))
        if campaign:
            print("Prolific STUDY_ID filter:", campaign)
        print("Coverage:", dict(counts))
        a, b = analyze(subjects, label)
        reports.extend(a)
        trends.extend(b)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        write_aggregate_csv(args.out, "early_right_push_associations.csv", reports)
        write_aggregate_csv(args.out, "right_push_mean_trajectories.csv", trends)
        print("\nAggregate CSVs written to:", args.out)
    print("\nNotes: Differences after question k exclude the first k answers."
          " Early associations do not prove early answers cause final success."
          " All Δ values measure LSM index reconstruction, not participant belief change.")


if __name__ == "__main__":
    main()
