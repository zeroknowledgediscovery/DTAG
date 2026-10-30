#!/usr/bin/env python3
"""Export private, analysis-ready DTAG human-study results from the audited GCP archives.

Read-only Firestore/GCS. Uses the earlier complete audit PRIVATE_all_sessions.csv,
PRIVATE_participant_crosswalk.csv, and immutable GCS final.json objects.
Preserves original/follow-up/zero-calibration cohorts and *observed* intervention
arms separately. Partial sessions use actually archived answer objects; no fill-in.

Outputs (all PRIVATE): sessions.csv, steps.csv, questions.csv, assignments.csv,
flags.csv, PRIVATE_id_crosswalk.csv and manifest.json.

Pseudonymization is HMAC-SHA256 with a locally persisted secret. The secret and
all results must stay outside public Git. No human free-text is exported unless
--include-text is explicitly requested.

Run (from DTAG repository root):
  python3 human_study/scripts/export_dtag_analysis_data.py \
      --audit-dir /tmp/dtag_full_audit \
      --out /private/dtag_analysis_2026_10_30 \
      --key-file /private/dtag_analysis_key.bin --strict
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sys

from audit_all_dtag_prolific import gcloud_token, gcs_list, gcs_get_json, STUDY_CONFIGS

BUCKET = "pkcsaas-01-dtag-study-data"
MAP_FILE = Path(__file__).resolve().parents[1] / "config" / "prolific_campaign_map.json"
CID_DEM = "6ae37b8688d760488b8df1b0"
CID_REP = "6ae3d74f4c7ff7370986b1e4"
SCHEMAS = {
    "sessions.csv": (
        "session_uid","participant_uid","dtag_study_id","prolific_campaign_id",
        "recruitment_cohort","protocol","policy","consented","firestore_phase",
        "approval_status","source_class","firestore_adaptive_count",
        "archive_adaptive_count","observed_adaptive_steps","complete_20_archive",
        "baseline_index","last_observed_index","index_delta_baseline_to_last",
        "final_archived_index","final_delta_from_baseline","created_at",
        "updated_at","config_hash","source_final_object_uid"),
    "steps.csv": (
        "session_uid","participant_uid","dtag_study_id","prolific_campaign_id",
        "recruitment_cohort","protocol","policy","approval_status","step",
        "index","delta_from_baseline","index_before","observed_step_delta",
        "predicted_target_only_delta","observed_scope","predicted_scope",
        "accepted_assignment_count","source_question_uid","source_class"),
    "questions.csv": (
        "session_uid","participant_uid","dtag_study_id","prolific_campaign_id",
        "recruitment_cohort","policy","approval_status","question_uid",
        "phase","ordinal","step_zero_based","adaptive_step","target_variable",
        "question_text","native_response_value","missing_reason",
        "mapping_status","accepted_assignment_count","rejected_assignment_count",
        "conflict_count","confirmation_count","attention_passed",
        "response_elapsed_seconds","response_timestamp","index_before",
        "index_after","observed_step_delta","predicted_target_only_delta",
        "predicted_scope","observed_scope","source_object_uid",
        "raw_text_response"),
    "assignments.csv": (
        "session_uid","question_uid","dtag_study_id","prolific_campaign_id",
        "recruitment_cohort","policy","approval_status","phase","adaptive_step",
        "target_variable","mapped_variable","native_value","confidence",
        "revises_prior","prior_native_value","assignment_type","evidence"),
    "flags.csv": ("code","dtag_study_id","session_uid","detail"),
    "PRIVATE_id_crosswalk.csv": (
        "session_uid","participant_uid","dtag_study_id","dtag_session_id",
        "prolific_pid","prolific_study_id","prolific_session_id",
        "approval_status","source_class"),
}


def truth(x):
    return x is True or str(x).strip().lower() in ("true", "1", "yes")


def integer(x):
    if x is None or x == "":
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def finite(x):
    if x is None or x == "" or isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def diff(a, b):
    return a - b if a is not None and b is not None else None


def csv_read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha256(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def check_archive(obj):
    expected = obj.get("content_sha256")
    return bool(expected) and sha256({k:v for k,v in obj.items() if k!="content_sha256"}) == expected


def get_key(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if not path.is_file():
            raise ValueError("HMAC key path is not a file")
        key = path.read_bytes()
    else:
        key = os.urandom(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        print("Created persistent analysis key (back this up privately):", path, file=sys.stderr)
    if len(key) < 32:
        raise ValueError("Analysis HMAC key must have at least 32 bytes")
    if path.stat().st_mode & 0o077:
        raise ValueError("Analysis HMAC key is readable by group/other; chmod 600")
    return key


def pseudonym(key, kind, *parts):
    msg = kind + "\0" + "\0".join(str(x) for x in parts)
    return kind[:1] + hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()[:24]


def load_roster_crosswalk(path):
    approved = set()
    for r in csv_read(path):
        if not truth(r.get("matching_id_and_campaign")):
            continue
        cid = r.get("expected_campaign_id", "").strip()
        pid = r.get("prolific_pid", "").strip().lower()
        if not (cid and pid):
            continue
        approved.add((cid, pid))
    return approved


def source_index(bucket, bearer, studies):
    index = defaultdict(dict)
    for study in sorted(studies):
        print("Indexing archive objects:", study, file=sys.stderr)
        prefix = f"studies/{study}/sessions/"
        for kind, name in gcs_list(bucket, bearer, prefix=prefix):
            if kind != "object":
                continue
            rest = name[len(prefix):]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                continue
            sid, suffix = parts
            if (suffix == "final.json" or suffix == "events/assignment.json"
                    or (suffix.endswith(".json") and suffix.split("/",1)[0]
                        in ("baseline", "questions", "attention", "outcomes"))):
                index[(study,sid)][suffix] = name
    return index


def get_archives(rec, objects, getter, flag):
    study = rec["study_id"]; sid = rec["dtag_session_id"]
    paths = objects.get((study,sid),{})
    if "final.json" in paths:
        obj = getter(paths["final.json"])
        if not check_archive(obj):
            flag("INVALID_FINAL_CHECKSUM", study, sid, "final.json has invalid or absent content_sha256")
        q = obj.get("questions") or []
        if not isinstance(q,list):
            flag("INVALID_FINAL_QUESTIONS",study,sid,"final.json questions is not a list")
            q = []
        return obj, [dict(x) for x in q if isinstance(x,dict)], paths["final.json"], "final"
    qs=[]
    for suffix,name in sorted(paths.items()):
        if suffix.split("/",1)[0] not in ("baseline","questions","attention","outcomes"):
            continue
        a=getter(name)
        if not check_archive(a):
            flag("INVALID_ANSWER_CHECKSUM",study,sid,"Invalid checksum in "+name)
        q=a.get("question")
        if isinstance(q,dict) and q.get("status")=="answered":
            qs.append({**q, "_gcs_source":name})
    return None, qs, "", "partial" if qs else "no_archive"


def write_private(path, rows, schema):
    with path.open("x",encoding="utf-8",newline="") as f:
        os.chmod(path,0o600)
        writer=csv.DictWriter(f, fieldnames=schema, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def produce(records, approved, objects, getter, key, include_text=False, include_tests=False, strict=False):
    campaign_map=json.loads(MAP_FILE.read_text(encoding="utf-8"))["campaigns"]
    records=sorted(records,key=lambda r:(r["study_id"],r["dtag_session_id"]))
    rows={n:[] for n in SCHEMAS}
    flags=[]
    def flag(code, study, sid, message):
        flags.append({"code":code,"dtag_study_id":study,
                      "session_uid":pseudonym(key,"session",study,sid),
                      "detail":message})
    seen=set()
    roster_full=set()
    study_counts=Counter()
    for rec in records:
        study=str(rec.get("study_id") or "").strip()
        sid=str(rec.get("dtag_session_id") or "").strip()
        if not study or not sid:
            flag("AUDIT_ROW_MISSING_SESSION_ID",study,sid,"Missing audit study/session identifier")
            continue
        if (study,sid) in seen:
            flag("DUPLICATE_AUDIT_SESSION",study,sid,"Duplicate row in PRIVATE_all_sessions.csv")
            continue
        seen.add((study,sid))
        cfg=STUDY_CONFIGS.get(study)
        if cfg is None and not include_tests:
            continue
        study_counts[study]+=1
        campaign=str(rec.get("prolific_study_id") or "")
        pid=str(rec.get("prolific_pid") or "").strip().lower()
        arm=str(rec.get("policy") or "")
        cs=campaign_map.get(campaign, {})
        cohort=cs.get("cohort","unclassified")
        if campaign and campaign not in campaign_map:
            cohort="unverified_external_recruitment"
        protocol="zero_calibration" if cfg and cfg.get("baseline")==0 else (
            "six_question_calibration" if cfg else "unclassified_test_or_staging")
        status=("approved_paid" if study=="dtag-v3-nocal-right-2026-10" and (campaign,pid) in approved else
                "not_on_approved_invoice" if campaign in campaign_map else "unverified")
        suid=pseudonym(key,"session",study,sid)
        puid=pseudonym(key,"participant",pid) if pid else pseudonym(key,"missing",study,sid)
        final,questions,source,class_ = get_archives(rec,objects,getter,flag)
        # A Firestore 'complete' state is not interchangeable with a verified
        # final.json. Preserve this session in the inventory and flag the
        # missing GCS evidence instead of treating it as a recovered trajectory.
        if rec.get("phase") == "complete" and final is None:
            flag("FIRESTORE_COMPLETE_NO_GCS_FINAL",study,sid,
                 "Firestore says complete but immutable final.json is missing")
        if class_ == "no_archive" and integer(rec.get("adaptive_count_firestore")):
            flag("FIRESTORE_ANSWERS_NOT_RECOVERED",study,sid,
                 "Firestore records adaptive answers but neither finalized nor individual archived responses were found")
        if final:
            if final.get("study_id") != study or final.get("session_id") != sid:
                flag("ARCHIVE_ID_MISMATCH",study,sid,"Final archive study/session identifier mismatch")
            pf=final.get("prolific") or {}
            if pf.get("prolific_pid") and str(pf["prolific_pid"]).lower() != pid:
                flag("ARCHIVE_PROLIFIC_PID_MISMATCH",study,sid,"Final Prolific PID differs from audit")
            if pf.get("prolific_study_id") and pf["prolific_study_id"] != campaign:
                flag("ARCHIVE_CAMPAIGN_MISMATCH",study,sid,"Final Prolific campaign differs from audit")
            if final.get("policy") and final["policy"] != arm:
                flag("ARCHIVE_POLICY_MISMATCH",study,sid,"Final intervention arm differs from audit")
            if (campfire:=final.get("config_hash")) and rec.get("config_hash") and campfire!=rec["config_hash"]:
                flag("ARCHIVE_CONFIG_HASH_MISMATCH",study,sid,"Archive protocol hash differs from audit")
        if cs and arm and arm!=cs["push_policy"]:
            flag("COHORT_PUSH_MISMATCH",study,sid,f"Expected {cs['push_policy']}, actual {arm}")
        if cfg and cfg["expected_policy"]!="randomized" and arm and arm != cfg["expected_policy"]:
            flag("STUDY_PUSH_MISMATCH",study,sid,f"Expected {cfg['expected_policy']}, actual {arm}")
        baseline=finite((final or {}).get("baseline_index"))
        if baseline is None:
            baseline=finite(rec.get("baseline_index"))
        end=finite((final or {}).get("final_index"))
        questions=sorted(questions,key=lambda q:(integer(q.get("ordinal")) if integer(q.get("ordinal")) is not None else 10**6,
            str(q.get("question_id") or "")))
        step_index={}
        questions_count=0
        question_rows=[]
        mapping_rows=[]
        for q in questions:
            phase=str(q.get("phase") or "")
            ordinal=integer(q.get("ordinal"))
            rawstep=integer(q.get("step"))
            num=rawstep+1 if phase=="intervention" and rawstep is not None else None
            quid=pseudonym(key,"question",study,sid,q.get("question_id") or (phase,ordinal))
            result=q.get("index_result") or {}
            selection=q.get("selection") or {}
            mappings=q.get("accepted_assignments") or []
            if not isinstance(mappings,list):
                flag("INVALID_ASSIGNMENTS",study,sid,f"Question {phase}/{rawstep} assignments not a list")
                mappings=[]
            mapping_status=(q.get("response_interpretation") or {}).get("mapping_status") if isinstance(q.get("response_interpretation"),dict) else None
            interp=q.get("response_interpretation") if isinstance(q.get("response_interpretation"),dict) else {}
            before=finite(result.get("index_before"))
            after=finite(result.get("index_after"))
            delta=finite(result.get("observed_conditional_index_delta"))
            predicted=finite(result.get("predicted_model_delta"))
            if predicted is None:
                predicted=finite(selection.get("expected_delta"))
            if delta is None:
                delta=diff(after,before)
            if phase=="intervention":
                questions_count+=1
                if num is None or not 1<=num<=20:
                    flag("INVALID_INTERVENTION_STEP",study,sid,f"Invalid intervention step {rawstep}")
                elif num in step_index:
                    flag("DUPLICATE_INTERVENTION_STEP",study,sid,f"Repeated intervention step {num}")
                else:
                    step_index[num]={"index":after,"before":before,"delta":delta,
                        "predicted":predicted,"accepted":len(mappings),"uid":quid,
                        "predicted_scope":result.get("predicted_delta_scope") or "",
                        "observed_scope":result.get("observed_delta_scope") or ""}
            question_rows.append(dict(session_uid=suid,participant_uid=puid,dtag_study_id=study,
                prolific_campaign_id=campaign,recruitment_cohort=cohort,policy=arm,
                approval_status=status,question_uid=quid,phase=phase,ordinal=ordinal,
                step_zero_based=rawstep,adaptive_step=num,target_variable=q.get("target_variable"),
                question_text=q.get("displayed_wording") or "",
                native_response_value=q.get("response_value"),missing_reason=q.get("missing_reason"),
                mapping_status=mapping_status,accepted_assignment_count=len(mappings),
                rejected_assignment_count=len(interp.get("rejected") or []),
                conflict_count=len(interp.get("conflicts") or []),
                confirmation_count=len(interp.get("confirmations") or []),
                attention_passed=q.get("attention_passed"),
                response_elapsed_seconds=finite(q.get("response_elapsed_seconds")),
                response_timestamp=q.get("response_timestamp"),index_before=before,index_after=after,
                observed_step_delta=delta,predicted_target_only_delta=predicted,
                predicted_scope=result.get("predicted_delta_scope") or "",
                observed_scope=result.get("observed_delta_scope") or "",
                source_object_uid=(pseudonym(key,"source",q.get("_gcs_source") or source)
                    if (q.get("_gcs_source") or source) else ""),
                raw_text_response=q.get("raw_text_response") if include_text else ""))
            if mappings:
                for m in mappings:
                    if not isinstance(m,dict):
                        flag("INVALID_MAPPING_RECORD",study,sid,"Non-object accepted assignment")
                        continue
                    mapping_rows.append(dict(session_uid=suid,question_uid=quid,dtag_study_id=study,
                        prolific_campaign_id=campaign,recruitment_cohort=cohort,policy=arm,
                        approval_status=status,phase=phase,adaptive_step=num,
                        target_variable=q.get("target_variable"),mapped_variable=m.get("variable"),
                        native_value=m.get("native_value"),confidence=finite(m.get("confidence")),
                        revises_prior=truth(m.get("revises_prior")),prior_native_value=m.get("prior_native_value"),
                        assignment_type="explicit_multi_variable",evidence=m.get("evidence") if include_text else ""))
            elif phase in ("baseline","intervention") and q.get("response_value") is not None:
                # Earlier protocol: one native observation for the prompted target.
                mapping_rows.append(dict(session_uid=suid,question_uid=quid,dtag_study_id=study,
                    prolific_campaign_id=campaign,recruitment_cohort=cohort,policy=arm,
                    approval_status=status,phase=phase,adaptive_step=num,
                    target_variable=q.get("target_variable"),mapped_variable=q.get("target_variable"),
                    native_value=q.get("response_value"),confidence=None,
                    revises_prior=False,prior_native_value=None,assignment_type="legacy_single_value",
                    evidence=""))
        actual_steps=sorted(step_index)
        if actual_steps and actual_steps != list(range(1,max(actual_steps)+1)):
            flag("TRAJECTORY_STEP_GAP",study,sid,f"Stored steps {actual_steps} are noncontiguous")
        # Do not invent a trajectory baseline from Firestore metadata alone.
        # 'no_archive' means there are no immutable question observations to
        # anchor the trajectory. The baseline remains in sessions.csv for audit.
        if baseline is not None and class_ != "no_archive":
            rows["steps.csv"].append(dict(session_uid=suid,participant_uid=puid,
                dtag_study_id=study,prolific_campaign_id=campaign,recruitment_cohort=cohort,
                protocol=protocol,policy=arm,approval_status=status,step=0,index=baseline,
                delta_from_baseline=0,index_before=None,observed_step_delta=None,
                predicted_target_only_delta=None,observed_scope="",predicted_scope="",
                accepted_assignment_count=0,source_question_uid="",source_class=class_))
        for n in actual_steps:
            x=step_index[n]
            ix=x["index"]
            if ix is None:
                flag("INDEX_MISSING_AT_STEP",study,sid,f"Step {n} has no after-index")
                continue
            rows["steps.csv"].append(dict(session_uid=suid,participant_uid=puid,
                dtag_study_id=study,prolific_campaign_id=campaign,recruitment_cohort=cohort,
                protocol=protocol,policy=arm,approval_status=status,step=n,index=ix,
                delta_from_baseline=diff(ix,baseline),index_before=x["before"],
                observed_step_delta=x["delta"],predicted_target_only_delta=x["predicted"],
                observed_scope=x["observed_scope"],predicted_scope=x["predicted_scope"],
                accepted_assignment_count=x["accepted"],source_question_uid=x["uid"],
                source_class=class_))
        last=step_index[max(actual_steps)]["index"] if actual_steps else baseline
        complete=bool(final) and set(actual_steps)==set(range(1,21)) and all(
            step_index[k]["index"] is not None for k in range(1,21))
        if final and questions_count!=20 and cfg:
            flag("FINAL_QUESTION_COUNT_NOT_20",study,sid,f"Final intervention count {questions_count}")
        if complete and end is not None and last is not None and not math.isclose(end,last,abs_tol=1e-6,rel_tol=1e-6):
            flag("FINAL_ENDPOINT_MISMATCH",study,sid,f"Archive final index differs from Q20 after-index by {end-last:.6g}")
        if status=="approved_paid" and complete:
            roster_full.add((campaign,pid))
        rows["sessions.csv"].append(dict(session_uid=suid,participant_uid=puid,
            dtag_study_id=study,prolific_campaign_id=campaign,recruitment_cohort=cohort,
            protocol=protocol,policy=arm,consented=truth(rec.get("consented")),
            firestore_phase=rec.get("phase"),approval_status=status,source_class=class_,
            firestore_adaptive_count=integer(rec.get("adaptive_count_firestore")),
            archive_adaptive_count=integer(rec.get("adaptive_count_archive")),
            observed_adaptive_steps=len(actual_steps),complete_20_archive=complete,
            baseline_index=baseline,last_observed_index=last,
            index_delta_baseline_to_last=diff(last,baseline),
            final_archived_index=end,final_delta_from_baseline=diff(end,baseline),
            created_at=rec.get("created_at"),updated_at=rec.get("updated_at"),
            config_hash=rec.get("config_hash"),source_final_object_uid=(
                pseudonym(key,"source",source) if source else "")))
        rows["questions.csv"].extend(question_rows)
        rows["assignments.csv"].extend(mapping_rows)
        rows["PRIVATE_id_crosswalk.csv"].append(dict(session_uid=suid,
            participant_uid=puid,dtag_study_id=study,dtag_session_id=sid,
            prolific_pid=pid,prolific_study_id=campaign,
            prolific_session_id=rec.get("prolific_session_id"),
            approval_status=status,source_class=class_))
        if status=="approved_paid" and not complete:
            flag("APPROVED_PARTICIPANT_NO_COMPLETE_TRAJECTORY",study,sid,
                 "Approved invoice participant missing full Q1..Q20 archive")
    rows["flags.csv"]=flags
    approved_recent={(c,p) for c,p in approved if c in (CID_DEM,CID_REP)}
    missing=approved_recent-roster_full
    if missing:
        flags.append(dict(code="APPROVED_ROSTER_UNMATCHED",dtag_study_id="dtag-v3-nocal-right-2026-10",
            session_uid="",detail=f"{len(missing)} approved participants not found with complete 20-step final"))
    counts={"sessions":len(rows["sessions.csv"]),"questions":len(rows["questions.csv"]),
            "steps":len(rows["steps.csv"]),"assignments":len(rows["assignments.csv"]),
            "complete_20_archive":sum(truth(r["complete_20_archive"]) for r in rows["sessions.csv"]),
            "studies":dict(sorted(study_counts.items())),
            "approved_recent_total":len(approved_recent),
            "approved_recent_complete_20":len(roster_full&approved_recent),
            "approved_recent_by_campaign":{
                cid:{"approved":sum(c==cid for c,p in approved_recent),
                     "complete20":sum(c==cid for c,p in roster_full)}
                for cid in (CID_DEM,CID_REP)},
            "flag_counts":dict(sorted(Counter(f["code"] for f in flags).items()))}
    wrong_roster_count = any(counts["approved_recent_by_campaign"][cid]["approved"] != 15
                             for cid in (CID_DEM, CID_REP))
    if wrong_roster_count:
        flags.append(dict(code="INCOMPLETE_APPROVED_ROSTER_SOURCE",dtag_study_id="",session_uid="",
                          detail="Expected exactly 15 approved PIDs in each latest campaign crosswalk"))
        counts["flag_counts"] = dict(sorted(Counter(f["code"] for f in flags).items()))
    return rows,counts, bool((missing or wrong_roster_count) and strict)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit-dir",type=Path,required=True,help="Folder from audit_all_dtag_prolific.py")
    ap.add_argument("--out",type=Path,required=True,help="Fresh PRIVATE output folder; must not exist")
    ap.add_argument("--key-file",type=Path,required=True,help="Persistent private >=32-byte HMAC key; generated if missing")
    ap.add_argument("--bucket",default=BUCKET)
    ap.add_argument("--include-text",action="store_true",help="Include human raw responses and mapping evidence (highly sensitive)")
    ap.add_argument("--include-tests",action="store_true",help="Include pilot, staging and GCP test sessions")
    ap.add_argument("--strict",action="store_true",help="Fail if any approved recent PID lacks 20-step archived trajectory")
    ap.add_argument("--offline-fixture",type=Path,help=argparse.SUPPRESS)
    args=ap.parse_args()
    if args.out.exists():
        ap.error(f"Output exists; refusing overwrite: {args.out}")
    # Never write under git working tree.
    repo=Path(__file__).resolve().parents[2]
    if args.out.resolve().is_relative_to(repo):
        ap.error("Output must be outside the DTAG Git repository")
    if args.key_file.resolve().is_relative_to(repo):
        ap.error("Key must be outside the DTAG Git repository")
    records=csv_read(args.audit_dir/"PRIVATE_all_sessions.csv")
    approved=load_roster_crosswalk(args.audit_dir/"PRIVATE_participant_crosswalk.csv")
    if args.offline_fixture:
        fixture=json.loads(args.offline_fixture.read_text())
        objects={}
        getter=lambda name: fixture["objects"][name]
        for x in fixture["session_objects"]:
            objects[(x["study_id"],x["session_id"])]=x["entries"]
    else:
        token=gcloud_token()
        all_studies={r["study_id"] for r in records if args.include_tests or r["study_id"] in STUDY_CONFIGS}
        objects=source_index(args.bucket,token,all_studies)
        getter=lambda name: gcs_get_json(args.bucket,name,token)
    key=get_key(args.key_file)
    rows,counts,failed=produce(records,approved,objects,getter,key,args.include_text,args.include_tests,args.strict)
    args.out.mkdir(parents=True,mode=0o700)
    os.chmod(args.out,0o700)
    for file,schema in SCHEMAS.items():
        write_private(args.out/file,rows[file],schema)
    manifest={"schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
         "dataset_kind":"PRIVATE pseudonymized human-response research export",
         "source_audit_folder":str(args.audit_dir.resolve()),
         "gcs_bucket":args.bucket,"count":counts,
         "methods":{"step":"0 is the recorded model baseline; adaptive steps 1-20 represent actually answered questions only",
             "approved_status":"Approved paid PIDs matched using the earlier private Prolific PDF audit crosswalk",
             "participant_uid":"HMAC-SHA256 of Prolific PID with private reusable key; different key yields different identifiers",
             "predicted_delta":"Selected-target-only projection; not directly commensurable with all-assignment observed delta",
             "observed_delta":"LSM index conditioned on all accepted native survey-variable assignments, not human belief change"},
         "free_text_included":args.include_text,"pilot_and_test_included":args.include_tests,
         "source_records_exclude_unarchived_responses":True,
         "source_audit_csv_sha256":hashlib.sha256(
             (args.audit_dir/"PRIVATE_all_sessions.csv").read_bytes()).hexdigest(),
         "analysis_key_id":pseudonym(key,"key_id","dtag-analysis-key"),
         "privacy":"All CSVs PRIVATE. Never commit this directory, analysis HMAC key, or PDF rosters to public Git."}
    with (args.out/"manifest.json").open("x",encoding="utf-8") as f:
        os.chmod(args.out/"manifest.json",0o600)
        json.dump(manifest,f,indent=2);f.write("\n")
    print("\nDTAG ANALYSIS EXPORT (private)")
    for f in SCHEMAS:
        print(f"{f:27s} {len(rows[f]):5d} rows")
    print("Approved recent full Q20 archives:",counts["approved_recent_complete_20"],"/",counts["approved_recent_total"])
    print("Warnings:",counts["flag_counts"])
    print("Saved:",args.out)
    if failed:
        raise SystemExit("STRICT FAILURE: one or more approved participants lacks a complete 20-step archive")


if __name__=="__main__":
    main()