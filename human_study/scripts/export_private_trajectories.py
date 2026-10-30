#!/usr/bin/env python3
"""Package archived DTAG model-index trajectories for reproducible private analysis.

Input: private analysis export (sessions.csv, steps.csv), already pseudonymized
with the investigator's persistent HMAC key. Output: a NEW private directory
containing session-level wide/long trajectories, group-step aggregates, and a
checksum manifest. All 21 indices I0..I20 are retained where observed.

Default includes ALL completed production study arms, including calibrated
Left/Right/Neutral/Random and zero-calibration DEM/REP cohorts. Partials can be
included with --include-partial; unarchived Firestore-only records are excluded.
Private per-session trajectories MUST NOT be committed to the public DTAG repo.
This script never touches Firestore/GCS and writes no human response text.

Example:
 python3 human_study/scripts/export_private_trajectories.py \
   --analysis-dir ~/private/dtag-analysis-2026-10-30-restored \
   --out ~/private/dtag-trajectories-2026-10-30-restored
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean

EPS = 1e-10
STEPS = 20
EXPECTED_STUDIES = frozenset({
    "prolific-v3-human-opinions-2026-10",
    "prolific-v3-left-followup-2026-10",
    "prolific-v3-right-followup-2026-10",
    "dtag-v3-nocal-left-2026-10",
    "dtag-v3-nocal-right-2026-10",
})

INFO = [
    "session_uid", "participant_uid", "dtag_study_id",
    "prolific_campaign_id", "recruitment_cohort", "protocol", "policy",
    "source_class", "trajectory_status", "initial_ideology",
    "n_adaptive_observed", "q4_resistance_flag", "endpoint_directional_success",
    "endpoint_correct_resistance", "endpoint_extended_success",
]
WIDE_FIELDS = INFO + [f"i{t:02}" for t in range(STEPS + 1)] + [
    f"d{t:02}" for t in range(STEPS + 1)]
LONG_FIELDS = [
    "session_uid", "dtag_study_id", "recruitment_cohort", "protocol",
    "policy", "initial_ideology", "trajectory_status", "step", "index",
    "delta_from_baseline", "index_before", "observed_step_delta",
    "predicted_target_only_delta", "accepted_assignment_count",
    "observed_scope", "predicted_scope", "source_class",
]
GROUP_FIELDS = [
    "protocol", "dtag_study_id", "recruitment_cohort", "policy",
    "initial_ideology", "step", "n_observed", "mean_index",
    "mean_delta_from_baseline",
]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def num(x):
    if x is None or str(x).strip() == "":
        raise ValueError("Missing model index in observed trajectory")
    f = float(x)
    if not math.isfinite(f):
        raise ValueError("Nonfinite model index")
    return f


def optional_num(x):
    if x is None or str(x).strip() == "":
        return None
    return num(x)


def is_true(s):
    return str(s).lower() in ("true", "1", "yes")


def ideology(i0, protocol):
    if protocol != "six_question_calibration":
        return "empty_state_not_human_phenotype"
    return "initially_left" if i0 < -EPS else "initially_right" if i0 > EPS else "initially_center"


def save_csv(path, columns, rows):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                   "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(analysis_dir, out, include_partial=False, expect_complete=None):
    sess = read_csv(analysis_dir / "sessions.csv")
    steps = read_csv(analysis_dir / "steps.csv")
    if not sess or not steps:
        raise ValueError("Missing sessions or steps in private analysis export")
    if out.exists():
        raise ValueError("Output exists; refusing overwrite: " + str(out))
    # Check both canonical paths (including symlinks) so a private export cannot
    # accidentally appear inside the public checkout.
    repo = Path(__file__).resolve().parents[2]
    if out.resolve().is_relative_to(repo):
        raise ValueError("Private output cannot be inside DTAG repository")
    per_session = defaultdict(dict)
    for row in steps:
        uid = row["session_uid"]
        t = int(row["step"])
        if not 0 <= t <= STEPS:
            raise ValueError("Invalid observed adaptive step")
        if t in per_session[uid]:
            raise ValueError("Duplicate step in steps.csv: " + uid)
        if row.get("source_class") == "no_archive":
            # Reject rows from a legacy pre-recovery exporter that fabricated
            # a baseline from Firestore metadata alone.
            continue
        per_session[uid][t] = row

    wide, long, aggregate = [], [], defaultdict(lambda: [[], []])
    counts = Counter()
    seen = set()
    for s in sess:
        if s.get("dtag_study_id") not in EXPECTED_STUDIES:
            continue
        uid = s["session_uid"]
        if uid in seen:
            raise ValueError("Duplicate production session in sessions.csv")
        seen.add(uid)
        if s.get("source_class") not in ("final", "partial"):
            continue
        complete = is_true(s.get("complete_20_archive"))
        if not complete and not include_partial:
            continue
        indexed = per_session.get(uid, {})
        if not indexed:
            raise ValueError("Archived session has no saved indices")
        observed = sorted(t for t in indexed if t > 0)
        if 0 not in indexed:
            raise ValueError("Archived trajectory missing baseline index")
        if complete and sorted(indexed) != list(range(STEPS + 1)):
            raise ValueError("Finalized 20/20 participant missing some indices")
        if len(observed) != int(s["observed_adaptive_steps"]):
            raise ValueError("Mismatch between session observed count and trajectory")
        i0 = num(indexed[0]["index"])
        if abs(i0 - num(s["baseline_index"])) > 1e-9:
            raise ValueError("Baseline index differs from sessions.csv")
        if complete and abs(num(indexed[STEPS]["index"]) -
                            num(s["final_archived_index"])) > 1e-9:
            raise ValueError("Final index differs from GCS final.json")
        prot = s["protocol"]
        arm = s["policy"]
        lean = ideology(i0, prot)
        is_target = prot == "six_question_calibration" and arm == "right" and lean == "initially_left"
        q4 = num(indexed[4]["index"]) if 4 in indexed else None
        i20 = num(indexed[STEPS]["index"]) if complete else None
        resistant = q4 is not None and (q4 - i0)/4 <= EPS if is_target else None
        success = ((i20-i0) < -EPS if arm == "left" else
                   (i20-i0) > EPS if arm == "right" else None) if i20 is not None else None
        correct_res = bool(resistant and (i20-i0) <= EPS) if is_target and i20 is not None else None
        extended = (success or bool(correct_res)) if arm == "right" and i20 is not None else None
        info = {
            "session_uid":uid, "participant_uid":s["participant_uid"],
            "dtag_study_id":s["dtag_study_id"],
            "prolific_campaign_id":s["prolific_campaign_id"],
            "recruitment_cohort":s["recruitment_cohort"],
            "protocol":prot, "policy":arm, "source_class":s["source_class"],
            "trajectory_status":"complete_20_archive" if complete else "partial_archive",
            "initial_ideology":lean,
            "n_adaptive_observed":len(observed),
            "q4_resistance_flag":resistant if is_target and q4 is not None else "",
            "endpoint_directional_success":success if success is not None else "",
            "endpoint_correct_resistance":correct_res if correct_res is not None else "",
            "endpoint_extended_success":extended if extended is not None else "",
        }
        w = dict(info)
        for t in range(STEPS + 1):
            idx = num(indexed[t]["index"]) if t in indexed else None
            w[f"i{t:02}"] = idx if idx is not None else ""
            w[f"d{t:02}"] = idx - i0 if idx is not None else ""
            if idx is None:
                continue
            r = indexed[t]
            long.append({
                "session_uid":uid,"dtag_study_id":s["dtag_study_id"],
                "recruitment_cohort":s["recruitment_cohort"],
                "protocol":prot,"policy":arm,"initial_ideology":lean,
                "trajectory_status":info["trajectory_status"],
                "step":t,"index":idx,"delta_from_baseline":idx-i0,
                "index_before":r.get("index_before") or "",
                "observed_step_delta":r.get("observed_step_delta") or "",
                "predicted_target_only_delta":r.get("predicted_target_only_delta") or "",
                "accepted_assignment_count":r.get("accepted_assignment_count") or "",
                "observed_scope":r.get("observed_scope") or "",
                "predicted_scope":r.get("predicted_scope") or "",
                "source_class":s["source_class"],
            })
            key=(prot,s["dtag_study_id"],s["recruitment_cohort"],arm,lean,t)
            aggregate[key][0].append(idx)
            aggregate[key][1].append(idx-i0)
        wide.append(w)
        counts["complete" if complete else "partial"] += 1
        counts[(prot,arm)] += 1

    if expect_complete is not None and counts["complete"] != expect_complete:
        raise ValueError(
            f"Expected {expect_complete} complete sessions, found {counts['complete']}; "
            "no output written")
    if not wide:
        raise ValueError("No archived trajectories selected")
    wide.sort(key=lambda r:(r["dtag_study_id"],r["session_uid"]))
    long.sort(key=lambda r:(r["dtag_study_id"],r["session_uid"],r["step"]))
    groups=[]
    for key, (indexes, deltas) in sorted(aggregate.items()):
        groups.append(dict(zip(GROUP_FIELDS[:6],key),
                           n_observed=len(indexes),mean_index=fmean(indexes),
                           mean_delta_from_baseline=fmean(deltas)))
    out.mkdir(mode=0o700, parents=True)
    os.chmod(out,0o700)
    outputs={
        "trajectories_wide_PRIVATE.csv":(WIDE_FIELDS,wide),
        "trajectories_long_PRIVATE.csv":(LONG_FIELDS,long),
        "trajectories_group_step_PRIVATE.csv":(GROUP_FIELDS,groups),
    }
    for filename,(fields,records) in outputs.items():
        save_csv(out / filename,fields,records)
    metadata={
        "schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
        "source_analysis_manifest_sha256":sha256(analysis_dir / "manifest.json"),
        "scope":"private session-level pseudonymized model-index trajectories",
        "counts":{"complete":counts["complete"],"partial":counts["partial"],
                  "session_by_protocol_policy":{f"{x[0]}/{x[1]}":n for x,n in counts.items()
                            if isinstance(x,tuple)}},
        "fields":{"i00":"Index immediately after calibration or empty-state initialization",
                  "i01_i20":"Observed index after each adaptive question",
                  "d00_d20":"Each observed index minus I0",
                  "q4_resistance_flag":"Only calibrated initially-left Right-push sessions"},
        "records":{"wide":len(wide),"long":len(long),"group_step":len(groups)},
        "files_sha256":{name:sha256(out/name) for name in outputs},
        "privacy":"PRIVATE; no Prolific IDs or response text. Never commit these files to public Git.",
    }
    name="trajectory_manifest_PRIVATE.json"
    with os.fdopen(os.open(out/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),
                   "w",encoding="utf-8") as f:
        json.dump(metadata,f,indent=2,sort_keys=True)
        f.write("\n")
    print("DTAG PRIVATE TRAJECTORY EXPORT")
    print("Complete:",counts["complete"],"partial:",counts["partial"])
    print("By protocol/arm:",metadata["counts"]["session_by_protocol_policy"])
    print("Rows: wide",len(wide),"; long",len(long),"; group-step",len(groups))
    print("Saved:",out)
    print("Do not add participant-level trajectory CSVs to public Git.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--analysis-dir",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--include-partial",action="store_true",
                   help="Include partial sessions with only actually observed steps; future steps remain blank")
    p.add_argument("--expect-complete",type=int,
                   help="Abort without writing if completed-session count differs")
    a=p.parse_args()
    export(a.analysis_dir.expanduser(),a.out.expanduser(),
           include_partial=a.include_partial,expect_complete=a.expect_complete)


if __name__=="__main__":
    main()
