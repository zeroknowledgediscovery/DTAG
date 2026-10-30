#!/usr/bin/env python3
"""Read-only check of the analysis export against the frozen 2026-10-28 TeX results.

This checks exact original four-arm completion counts, unchanged completed
Left/Neutral/Random endpoint means and baseline signs, step-20 data coherence,
and the paid 15+15 recent recruitment. It does NOT incorrectly assume that
the current 31-person fixed-Right follow-up is the historical 10-person cohort.

No identifiers, responses or participant-level outputs are printed or stored.

Usage:
  python3 human_study/scripts/compare_analysis_to_tex.py \\
    --analysis-dir ~/private/dtag-analysis-2026-10-30 \\
    --tex-dir tex/Figures
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
import math
from pathlib import Path
import sys

ORIGINAL="prolific-v3-human-opinions-2026-10"
FIXED_LEFT="prolific-v3-left-followup-2026-10"
FIXED_RIGHT="prolific-v3-right-followup-2026-10"
NOCAL_RIGHT="dtag-v3-nocal-right-2026-10"
CALIBRATED={ORIGINAL,FIXED_LEFT,FIXED_RIGHT}
DEMO="6ae37b8688d760488b8df1b0"
REPO="6ae3d74f4c7ff7370986b1e4"
EXPECTED_ORIGINAL={"left":5,"right":7,"neutral":7,"random":5}

def csvrows(path):
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

def number(v):
    if v in ("", None):
        return None
    try:
        result=float(v)
    except (TypeError,ValueError):
        return None
    return result if math.isfinite(result) else None

def complete(r):
    return r.get("complete_20_archive","").strip().lower()=="true"

def compare(data,tex,steps,legacy_trajectories):
    problems=[]
    warnings=[]
    all_completes=[r for r in data if complete(r)]
    calib=[r for r in all_completes if r["dtag_study_id"] in CALIBRATED]
    zero=[r for r in all_completes if r["dtag_study_id"]==NOCAL_RIGHT]
    print("Current 20-answer archived calibrated sessions:",len(calib))
    print("Current 20-answer archived zero-calibration Right sessions:",len(zero))
    original=Counter(r["policy"] for r in all_completes if r["dtag_study_id"]==ORIGINAL)
    print("Original randomized arm counts:",dict(sorted(original.items())))
    if original!=Counter(EXPECTED_ORIGINAL):
        problems.append("Original randomized 24-completer arm counts no longer match frozen TeX")
    if len(calib)!=70:
        warnings.append(f"Current calibrated count is {len(calib)}, compared with the reported 70")
    if len(zero)!=31:
        warnings.append(f"Current zero-calibration complete count is {len(zero)}, compared with the reported 31")

    # Matching TeX table is only expected for arms with no additions.
    byarm=defaultdict(list)
    for r in calib:
        byarm[r["policy"].lower()].append(r)
    texby={r["arm"].strip().lower():r for r in tex}
    print("\nFrozen TeX vs current archive (completed sessions only):")
    print(f"{'Arm':9} {'old n':>6} {'new n':>6} {'old mean':>12} {'new mean':>12}  Assessment")
    for arm in ("left","right","neutral","random"):
        rows=byarm[arm]
        old=texby[arm]
        oldn=int(old["n_completed"])
        oldmean=float(old["mean_endpoint_change"])
        vals=[]
        neg=pos=zero_baselines=0
        for r in rows:
            baseline=number(r.get("baseline_index"))
            end=number(r.get("final_archived_index"))
            if baseline is None or end is None:
                problems.append(f"{arm}: missing baseline/final archived index")
                continue
            vals.append(end-baseline)
            neg+=baseline<0;pos+=baseline>0;zero_baselines+=baseline==0
        mean=sum(vals)/len(vals) if vals else None
        if arm=="right":
            assessment="CHANGED COHORT: historical 10 fixed-Right identities needed"
            if len(rows)!=38:
                warnings.append(f"Right current n={len(rows)}, expected 7 original + 31 follow-up = 38")
        else:
            if len(rows)!=oldn or mean is None:
                problems.append(f"{arm}: completed count/current means unavailable or changed")
                assessment="MISMATCH"
            elif neg!=int(old["n_baseline_negative"]) or pos!=int(old["n_baseline_positive"]) or zero_baselines:
                problems.append(f"{arm}: baseline sign counts differ from published table")
                assessment="MISMATCH"
            elif not math.isclose(mean,oldmean,rel_tol=0,abs_tol=1e-8):
                problems.append(f"{arm}: endpoint mean differs by {mean-oldmean:+.12g}")
                assessment="MISMATCH"
            else:
                assessment="MATCH (n, baseline signs, mean)"
        print(f"{arm:9} {oldn:6} {len(rows):6} {oldmean:+12.6f} "
              f"{mean if mean is not None else float('nan'):+12.6f}  {assessment}")

    paid={cid:[r for r in zero if r.get("prolific_campaign_id")==cid
          and r.get("approval_status")=="approved_paid"] for cid in (DEMO,REPO)}
    nonpaid=Counter(r.get("prolific_campaign_id") for r in zero
        if r.get("approval_status")!="approved_paid")
    print("\nNew zero-calibration Right, approved 20-answer archives:")
    for cid,label in ((DEMO,"Democratic"),(REPO,"Republican")):
        n=len(paid[cid]);print(f"  {label}: {n}/15")
        if n!=15: problems.append(f"{label}: approved complete n={n}, expected 15")
    print("  Additional non-approved finalized archives by campaign:",
          {("DEM" if k==DEMO else "REP" if k==REPO else str(k)):v for k,v in nonpaid.items()})
    if nonpaid != Counter({REPO:1}):
        warnings.append("Additional non-approved archive distribution changed from Oct 30 output")

    complete_by_uid={r["session_uid"]:r for r in all_completes}
    q20=defaultdict(list)
    for r in steps:
        if r.get("step")=="20":
            q20[r["session_uid"]].append(r)
    for uid,r in complete_by_uid.items():
        matches=q20.get(uid,[])
        if len(matches)!=1:
            problems.append("Missing or duplicate question-20 row in steps.csv")
            continue
        from_step=number(matches[0].get("index"))
        from_session=number(r.get("final_archived_index"))
        if from_step is None or from_session is None or not math.isclose(
            from_step,from_session,rel_tol=1e-8,abs_tol=1e-8):
            problems.append("Archived final endpoint differs from steps.csv Q20")
    print("\nArchived endpoint-vs-step20 records checked:",len(complete_by_uid))
    # Stepwise trajectories include partial respondents, unlike the Q20 endpoints.
    # Compare only the three historically unchanged arms; bootstrap CIs can shift
    # when another arm's sample size changes in the shared-seed generator.
    allcalib={r["session_uid"] for r in data if r["dtag_study_id"] in CALIBRATED}
    stepgroups=defaultdict(list)
    for row in steps:
        if row.get("session_uid") not in allcalib:
            continue
        arm=row.get("policy","").lower()
        t=row.get("step")
        val=number(row.get("delta_from_baseline"))
        if arm in ("left","neutral","random") and t is not None and val is not None:
            stepgroups[(arm,int(t))].append(val)
    print("\nFrozen figure vs current stepwise trajectory (Left/Neutral/Random):")
    for arm in ("left","neutral","random"):
        count_errors=mean_errors=0
        for frozen in legacy_trajectories[arm]:
            t=int(frozen["step"]); v=stepgroups[(arm,t)]
            oldn=int(frozen["n"]); oldmean=float(frozen["mean"])
            if len(v)!=oldn:
                count_errors+=1
            if not v or not math.isclose(sum(v)/len(v),oldmean,rel_tol=0,abs_tol=1e-8):
                mean_errors+=1
        if count_errors or mean_errors:
            warnings.append(f"{arm}: frozen figure differs at {count_errors} step counts and {mean_errors} step means (check partial-session membership)")
            print(f"  {arm}: DIFFERENCES — {count_errors} step counts, {mean_errors} means")
        else:
            print(f"  {arm}: all 21 step counts and means MATCH")
    print("\nSTATUS:", "PASS with historical Right cohort unresolved" if not problems else "MISMATCH")
    if warnings:
        print("Warnings:")
        for w in warnings:print(" -",w)
    if problems:
        print("Numerical inconsistencies:")
        for p in dict.fromkeys(problems):print(" -",p)
    print("\nCaution: the frozen Right n=17 statistic cannot be reproduced from")
    print("today's 38 Right sessions without the original 10 follow-up session IDs.")
    print("Zero-calibration sessions must be analyzed separately from six-baseline sessions.")
    return 1 if problems else 0

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analysis-dir",type=Path,required=True)
    ap.add_argument("--tex-dir",type=Path,default=Path("tex/Figures"))
    args=ap.parse_args()
    return compare(
       csvrows(args.analysis_dir/"sessions.csv"),
       csvrows(args.tex_dir/"humanstudy_arm_summary.csv"),
       csvrows(args.analysis_dir/"steps.csv"),
       {arm:csvrows(args.tex_dir/f"humanstudy_trajectory_{arm}.csv") for arm in ("left","neutral","random")})

if __name__=="__main__":
    raise SystemExit(main())
