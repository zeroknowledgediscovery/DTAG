#!/usr/bin/env python3
"""Score early Q4 Right-push resistance in archived *calibrated* DTAG cohorts.

Reads private analysis sessions.csv + steps.csv. Read only; outputs aggregates
without participant IDs or responses. The six-question baseline I0 is distinct
from the zero-calibration empty-state baseline; these studies are not pooled.

Primary, on initially negative baseline only (I0 < -EPS), Right policy:
    R4 := (I4 - I0)/4 <= q4_max_mean_delta
    Directional success := I20 - I0 > EPS
    True endpoint failure := I20 - I0 <= EPS
    Combined outcome := directional success OR (R4 AND endpoint failure)

Also evaluates whether R4 forecasts *later* Q4->Q20 nonmovement, using a
non-overlapping outcome window (although the windows share the Q4 index). The composite is a descriptive
policy-or-diagnosis score, NOT evidence of greater intervention effectiveness.

Usage:
  python3 human_study/scripts/score_q4_right_resistance.py \
    --analysis-dir ~/private/dtag-analysis-2026-10-30

Optional private aggregate output directory:
  --out ~/private/dtag-q4-resistance
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

CALIBRATED = {
    "prolific-v3-human-opinions-2026-10",
    "prolific-v3-left-followup-2026-10",
    "prolific-v3-right-followup-2026-10",
}
EPS = 1e-10


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Missing or nonnumeric model index {value!r}") from None
    if not math.isfinite(result):
        raise ValueError(f"Nonfinite model index: {value!r}")
    return result


def rate(count, total):
    return f"{count}/{total} ({100*count/total:.1f}%)" if total else "0/0 (n/a)"


def load_complete_sessions(analysis_dir):
    sessions = read_csv(analysis_dir / "sessions.csv")
    steps = read_csv(analysis_dir / "steps.csv")
    by_session = defaultdict(dict)
    for row in steps:
        uid = row["session_uid"]
        t = int(row["step"])
        if t in by_session[uid]:
            raise ValueError(f"Duplicate step {t} for one session; stop and audit")
        by_session[uid][t] = number(row["index"])

    records = []
    uids = set()
    for r in sessions:
        if r["dtag_study_id"] not in CALIBRATED:
            continue
        if r.get("policy") not in ("left", "right"):
            continue
        if r.get("complete_20_archive", "").lower() != "true":
            continue
        uid = r["session_uid"]
        if uid in uids:
            raise ValueError("Duplicate completed session record; stop and audit")
        uids.add(uid)
        idx = by_session.get(uid, {})
        if set(idx) != set(range(21)):
            raise ValueError("A verified complete session lacks exactly steps 0..20; stop and audit")
        i0, i4, i20 = idx[0], idx[4], idx[20]
        if not math.isclose(i0, number(r["baseline_index"]), abs_tol=1e-9, rel_tol=0):
            raise ValueError("Step 0 disagrees with archived session baseline")
        if not math.isclose(i20, number(r["final_archived_index"]), abs_tol=1e-9, rel_tol=0):
            raise ValueError("Step 20 disagrees with archived session final")
        phenotype = "Initially Left" if i0 < -EPS else "Initially Right" if i0 > EPS else "At center"
        displacement = i20 - i0
        directional_success = displacement < -EPS if r["policy"] == "left" else displacement > EPS
        records.append(dict(session_uid=uid, participant_uid=r.get("participant_uid"),
                            study_id=r["dtag_study_id"], policy=r["policy"],
                            phenotype=phenotype, i0=i0, i4=i4, i20=i20,
                            displacement=displacement, directional_success=directional_success))
    return records


def contingency(rows, *, resistant_key, failed_key):
    # Resistance is the positive class, non-rightward movement is the endpoint label.
    tp = sum(r[resistant_key] and r[failed_key] for r in rows)
    fp = sum(r[resistant_key] and not r[failed_key] for r in rows)
    fn = sum(not r[resistant_key] and r[failed_key] for r in rows)
    tn = sum(not r[resistant_key] and not r[failed_key] for r in rows)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "sensitivity": tp / (tp + fn) if tp + fn else None,
            "specificity": tn / (tn + fp) if tn + fp else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "accuracy": (tp + tn) / len(rows) if rows else None}


def analyze(records, threshold):
    for r in records:
        r["resistant_q4"] = (r["i4"] - r["i0"]) / 4 <= threshold + EPS
        r["final_right_failure"] = r["i20"] - r["i0"] <= EPS
        r["later_right_failure"] = r["i20"] - r["i4"] <= EPS
        r["resistance_correct"] = (r["policy"] == "right" and
                                   r["phenotype"] == "Initially Left" and
                                   r["resistant_q4"] and r["final_right_failure"])
        r["extended_success"] = r["directional_success"] or r["resistance_correct"]

    left_initial_right_push = [r for r in records if r["phenotype"] == "Initially Left" and r["policy"] == "right"]
    diag_total = contingency(left_initial_right_push, resistant_key="resistant_q4", failed_key="final_right_failure")
    diag_later = contingency(left_initial_right_push, resistant_key="resistant_q4", failed_key="later_right_failure")
    outcomes = []
    groups = ["Initially Left", "Initially Right", "At center", "Overall"]
    for group in groups:
        subset = records if group == "Overall" else [r for r in records if r["phenotype"] == group]
        row = {"initial_phenotype": group}
        for arm in ("left", "right"):
            armrows = [r for r in subset if r["policy"] == arm]
            row[f"{arm}_n"] = len(armrows)
            row[f"{arm}_directional_success"] = sum(r["directional_success"] for r in armrows)
            row[f"{arm}_extended_success"] = sum(r["extended_success"] for r in armrows)
            row[f"{arm}_correct_resistance"] = sum(r["resistance_correct"] for r in armrows)
        if group != "At center" or any(row[x + "_n"] for x in ("left", "right")):
            outcomes.append(row)
    report = {
        "definition": {
            "population": "GCS finalized 20-answer calibrated DTAG sessions; session-level",
            "initial_left": "I0 < -1e-10",
            "q4_resistant": f"(I4 - I0)/4 <= {threshold} + 1e-10; initially left, right policy only",
            "rightward_success": "I20 - I0 > 1e-10",
            "extended_success": "directional_success OR (resistant_q4 AND NOT directional_success)",
            "later_validation": "predict I20-I4 <= 1e-10 from the Q4 resistance flag",
        },
        "n_calibrated_complete_directional": len(records),
        "table": outcomes,
        "initially_left_right_push_resistance_prediction": {
            "n": len(left_initial_right_push),
            "flagged_resistant_at_q4": sum(r["resistant_q4"] for r in left_initial_right_push),
            "correct_resistance_from_baseline": sum(r["resistance_correct"] for r in left_initial_right_push),
            "baseline_to_q20": diag_total,
            "q4_to_q20_subsequent_window": diag_later,
        },
        "duplicate_participant_uid_count": sum(n - 1 for n in Counter(
            r["participant_uid"] for r in records if r["participant_uid"]
        ).values() if n > 1),
    }
    return report


def print_report(report):
    print("\nDTAG calibrated directional-push success / Q4 resistance, GCS-verified 20/20")
    print("Q4 resistance: initially Left, Right policy; nonpositive mean Q1..Q4 signed displacement")
    print(f"{'Initial index':17} {'Left directional':24} {'Right directional':24} {'Right extended':24} {'Correct R4':12}")
    for t in report["table"]:
        nL = t["left_n"]; nR = t["right_n"]
        print(f"{t['initial_phenotype']:17} "
              f"{rate(t['left_directional_success'],nL):24} "
              f"{rate(t['right_directional_success'],nR):24} "
              f"{rate(t['right_extended_success'],nR):24} "
              f"{t['right_correct_resistance']:>6}/{nR:<5}")
    diag=report["initially_left_right_push_resistance_prediction"]
    print("\nInitially-Left / Right-push early-resistance classifier (Q4 only):")
    print("  Sessions:", diag["n"], "flagged by Q4:",diag["flagged_resistant_at_q4"])
    for label,key in (("Baseline→Q20 failure", "baseline_to_q20"),
                      ("Q4→Q20 subsequent nonmovement", "q4_to_q20_subsequent_window")):
        d=diag[key]
        print(" ",label,": TP",d["tp"],"FP",d["fp"],"FN",d["fn"],"TN",d["tn"])
        print("    precision:", f"{d['precision']:.1%}" if d["precision"] is not None else "n/a",
              "sensitivity:", f"{d['sensitivity']:.1%}" if d["sensitivity"] is not None else "n/a",
              "specificity:", f"{d['specificity']:.1%}" if d["specificity"] is not None else "n/a",
              "accuracy:", f"{d['accuracy']:.1%}" if d["accuracy"] is not None else "n/a")
    if report["duplicate_participant_uid_count"]:
        print("WARNING:",report["duplicate_participant_uid_count"],
              "additional sessions share a participant UID; results are per-session, not globally unique individuals")
    print("\nCAUTION: extended success mixes policy response with correct early resistance identification;")
    print("it is NOT a directional intervention success rate. Q4→Q20 is the more stringent forecast check.")
    print("Indices are model-inferred survey phenotypes, not verified changes in beliefs.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analysis-dir",required=True,type=Path)
    p.add_argument("--q4-max-mean-delta",type=float,default=0.0,
                   help="Maximum average signed rightward displacement per Q1..Q4 to flag early resistance (default: 0)")
    p.add_argument("--out",type=Path,
                   help="New private output directory for aggregate table CSV and diagnostics JSON")
    args=p.parse_args()
    if not math.isfinite(args.q4_max_mean_delta):
        p.error("--q4-max-mean-delta must be finite")
    records=load_complete_sessions(args.analysis_dir.expanduser())
    if not records:
        p.error("No complete calibrated Left/Right trajectories found")
    report=analyze(records,args.q4_max_mean_delta)
    print_report(report)
    if args.out:
        out=args.out.expanduser()
        if out.exists():
            p.error("Output directory exists; refusing overwrite")
        out.mkdir(mode=0o700,parents=True)
        with (out/"q4_resistance_table.csv").open("x",newline="",encoding="utf-8") as f:
            import os
            os.chmod(out/"q4_resistance_table.csv",0o600)
            fields=list(report["table"][0])
            writer=csv.DictWriter(f,fieldnames=fields)
            writer.writeheader();writer.writerows(report["table"])
        with (out/"q4_resistance_diagnostics.json").open("x",encoding="utf-8") as f:
            import os
            os.chmod(out/"q4_resistance_diagnostics.json",0o600)
            json.dump({k:v for k,v in report.items() if k!="table"},f,indent=2)
            f.write("\n")
        print("\nPrivate aggregate results:",out)


if __name__=="__main__":
    main()
