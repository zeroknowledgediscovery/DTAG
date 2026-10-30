#!/usr/bin/env python3
"""Reconcile ALL discoverable DTAG human studies against two Prolific payment PDFs.

Read only. No Cloud writes, no participant-response text exported. Requires:
  pip install PyMuPDF
  gcloud auth login                  # with Firestore and Storage read access

From the DTAG repository root, for example:
  python3 human_study/scripts/audit_all_dtag_prolific.py \
    --dem-pdf /secure/DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf \
    --rep-pdf /secure/REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf \
    --out /secure/dtag_audit_2026_10_30

IMPORTANT: PDFs are APPROVED-PAYMENT rosters, not full Prolific submission exports.
They do not independently establish the Prolific STUDY_ID from within the PDF.
We require BOTH an exact participant-ID match AND a matching stored STUDY_ID.

Outputs aggregate tables and a protected private participant-level crosswalk.
All findings are observations; they never alter the research database.
"""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# These two campaign IDs are INVESTIGATOR-DECLARED and must be checked against
# the Prolific campaign webpage; the PDF payment invoice does not print STUDY_ID.
CAMPAIGNS = {
    "6ae37b8688d760488b8df1b0": {
        "name": "Democratic recruitment / fixed right", "short": "DEM",
        "study": "dtag-v3-nocal-right-2026-10", "policy": "right",
        "pdf_title": "DTAG_right_DEM", "planned_slots": 15,
    },
    "6ae3d74f4c7ff7370986b1e4": {
        "name": "Republican recruitment / fixed right", "short": "REP",
        "study": "dtag-v3-nocal-right-2026-10", "policy": "right",
        "pdf_title": "DTAG_right_REP", "planned_slots": 15,
    },
}

# Instrument-defined baseline lengths, independent of observed assignments.
# If additional production studies are created, add their verified configuration.
STUDY_CONFIGS = {
    "prolific-v3-human-opinions-2026-10": {"baseline": 6, "expected_policy": "randomized", "class": "calibrated", "label": "Original four-arm Prolific"},
    "prolific-v3-left-followup-2026-10": {"baseline": 6, "expected_policy": "left", "class": "calibrated", "label": "Fixed Left follow-up"},
    "prolific-v3-right-followup-2026-10": {"baseline": 6, "expected_policy": "right", "class": "calibrated", "label": "Fixed Right follow-up"},
    "dtag-v3-nocal-left-2026-10": {"baseline": 0, "expected_policy": "left", "class": "zero calibration", "label": "Zero-calibration Left"},
    "dtag-v3-nocal-right-2026-10": {"baseline": 0, "expected_policy": "right", "class": "zero calibration", "label": "Zero-calibration Right (DEM+REP)"},
}

PID_RE = re.compile(r"(?<![a-fA-F0-9])(?:[a-fA-F0-9]{24})(?![a-fA-F0-9])")
FIRESTORE_FIELDS = (
    "session_id", "prolific.prolific_pid", "prolific.prolific_study_id",
    "prolific.prolific_session_id", "consent_accepted", "policy", "phase",
    "next_step", "attention_completed", "state.baseline_index", "state.current_index",
    "config_hash", "provenance_hash", "created_at", "updated_at", "pending_exports",
)


def extract_pdf(path: Path, expected_title: str) -> dict:
    try:
        import fitz  # PyMuPDF; PDF text layer, not OCR
    except ImportError as exc:
        raise SystemExit("Requires PyMuPDF: python3 -m pip install pymupdf") from exc
    doc = fitz.open(str(path))
    text = "\n".join(page.get_text(sort=True) for page in doc)
    # The approved-submissions table is bounded by its heading and total section.
    start = text.find("Approved Submissions")
    if start < 0:
        raise ValueError(f"{path.name}: cannot find Approved Submissions heading")
    # The PDFs do not present participant IDs in any other sections.
    ids = PID_RE.findall(text[start:])
    ids = [v.lower() for v in ids]
    if expected_title not in text:
        raise ValueError(f"{path.name}: missing expected study title {expected_title!r}")
    if len(ids) != 15 or len(set(ids)) != 15:
        raise ValueError(f"{path.name}: expected 15 unique approved participant IDs, found {len(ids)} rows / {len(set(ids))} unique")
    summary = re.search(r"Summary ID:\s*([A-Z0-9]+)", text)
    if not summary:
        raise ValueError(f"{path.name}: payment summary ID missing")
    reward = re.search(r"Participants' reward disbursements\s*\$([0-9,.]+)", text)
    if not reward or float(reward.group(1).replace(",", "")) != 165.0:
        raise ValueError(f"{path.name}: expected $165 total rewards for 15 approved participants")
    return {"pids": frozenset(ids), "pdf_title": expected_title,
            "summary_id": summary.group(1), "pdf_file": path.name,
            "reward_total_usd": 165.0, "approved": len(ids)}


def gcloud_token() -> str:
    try:
        return subprocess.check_output(["gcloud", "auth", "print-access-token"],
                  text=True, stderr=subprocess.PIPE, timeout=40).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Cannot obtain gcloud token. Run gcloud auth login.") from exc


def rest_json(url: str, bearer: str, *, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, headers={"Authorization": "Bearer " + bearer,
                  "Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urlopen(req, timeout=100) as f:
            return f.read().decode("utf-8")
    except HTTPError as exc:
        content = exc.read(400).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} at {url.split('?')[0]}: {content}") from exc


def parse_firestore_value(v):
    if "mapValue" in v:
        return {k: parse_firestore_value(x) for k,x in v["mapValue"].get("fields",{}).items()}
    if "arrayValue" in v:
        return [parse_firestore_value(x) for x in v["arrayValue"].get("values",[])]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    for k in ("booleanValue", "stringValue", "timestampValue"):
        if k in v:
            return v[k]
    return None


def extract_firestore_document(d: dict) -> dict | None:
    path = d.get("name", "")
    match = re.search(r"/documents/studies/([^/]+)/sessions/([^/]+)$", path)
    if not match:
        return None
    fields = {k:parse_firestore_value(v) for k,v in d.get("fields", {}).items()}
    return {"study": match.group(1), "sid": match.group(2), "fields":fields}


def scan_collection_group(project, database, bearer) -> list:
    """Exhaustive Firestore collection-group scan, including studies without parent docs.

    Firestore runQuery returns a stream of JSON objects (not a single JSON array).
    If the account lacks permissions/index, caller falls back to known-study scan.
    """
    uri = (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
           f"/databases/{quote(database, safe='()')}/documents:runQuery")
    # No filters: do not rely on a composite collection-group index.
    query = {"structuredQuery": {"from": [{"collectionId": "sessions", "allDescendants": True}],
             "select": {"fields": [{"fieldPath": s} for s in FIRESTORE_FIELDS]}}}
    text = rest_json(uri, bearer, body=query)
    objects = json.loads(text) if text.strip().startswith("[") else [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    result = []
    for obj in objects:
        if "document" in obj:
            d = extract_firestore_document(obj["document"])
            if d is not None:
                result.append(d)
    return result


def scan_one_study(project, database, study, bearer) -> list:
    uri = (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
           f"/databases/{quote(database, safe='()')}/documents/studies/"
           f"{quote(study, safe='')}/sessions")
    result, page = [], None
    while True:
        params = [("pageSize", "100")] + [("mask.fieldPaths", field) for field in FIRESTORE_FIELDS]
        if page:
            params.append(("pageToken", page))
        response = json.loads(rest_json(uri + "?" + urlencode(params), bearer))
        for obj in response.get("documents", []):
            d = extract_firestore_document(obj)
            if d is not None:
                result.append(d)
        page = response.get("nextPageToken")
        if not page:
            return result


def gcs_list(bucket, bearer, *, prefix="", delimiter=None):
    endpoint = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o"
    page = None
    while True:
        q = [("prefix", prefix), ("maxResults", "1000")]
        if delimiter:
            q.append(("delimiter", delimiter))
        if page:
            q.append(("pageToken", page))
        obj = json.loads(rest_json(endpoint + "?" + urlencode(q), bearer))
        for x in obj.get("items", []):
            yield ("object", x["name"])
        for pref in obj.get("prefixes", []):
            yield ("prefix", pref)
        page = obj.get("nextPageToken")
        if not page:
            break


def gcs_get_json(bucket, name, bearer):
    # JSON API media downloads, exact GCS object name URI encoded.
    uri = (f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}"
           f"/o/{quote(name,safe='')}?alt=media")
    return json.loads(rest_json(uri, bearer))


def gcs_discover_studies(bucket, bearer) -> set[str]:
    return {x[len("studies/"):-1] for kind,x in gcs_list(bucket,bearer,prefix="studies/",delimiter="/")
            if kind=="prefix" and x.startswith("studies/") and x.endswith("/")}


def read_gcs_finals(bucket, studies, bearer):
    finals = {}
    for study in sorted(studies):
        print(f"GCS archived finals: {study}", file=sys.stderr, flush=True)
        for kind,name in gcs_list(bucket,bearer,prefix=f"studies/{study}/sessions/"):
            if kind != "object" or not name.endswith("/final.json"):
                continue
            match = re.fullmatch(r"studies/([^/]+)/sessions/([^/]+)/final\.json", name)
            if not match:
                continue
            sid=match.group(2)
            data=gcs_get_json(bucket,name,bearer)
            finals[(study,sid)]=data
    return finals


def s(x):
    return str(x) if x is not None else ""


def parse_record(row, final=None):
    f = row["fields"] if row else {}
    a = final or {}
    prolific_f = f.get("prolific") or {}
    prolific_a = a.get("prolific") or {}
    study = row["study"] if row else s(a.get("study_id"))
    if not study:
        raise ValueError("Archive-only final has no study_id")
    sid = row["sid"] if row else s(a.get("session_id"))
    cfg=STUDY_CONFIGS.get(study,{})
    def get(k):
        return prolific_f.get(k) or prolific_a.get(k) or ""
    baseline_len=cfg.get("baseline")
    count = None
    if row and baseline_len is not None and f.get("next_step") is not None:
        count=int(f["next_step"])-int(f.get("attention_completed") or 0)-baseline_len
    qlist=a.get("questions") or []
    archived_count=sum(q.get("phase")=="intervention" and q.get("status") in (None,"answered") for q in qlist) if final else None
    if final and archived_count is not None and count is None:
        count=archived_count
    consent=f.get("consent_accepted") is True if row else bool(final)
    return {
        "study_id":study,"dtag_session_id":sid,
        "prolific_pid":s(get("prolific_pid")).lower(),
        "prolific_study_id":s(get("prolific_study_id")),
        "prolific_session_id":s(get("prolific_session_id")),
        "consented":consent,"phase":s(f.get("phase")) or ("archive_final_only" if final else "unknown"),
        "policy":s(f.get("policy") or a.get("policy")),
        "baseline_questions":baseline_len,"adaptive_count_firestore":count,
        "adaptive_count_archive":archived_count,
        "firestore_present":bool(row),"gcs_final_present":bool(final),
        "baseline_index":(f.get("state") or {}).get("baseline_index") if row else a.get("baseline_index"),
        "current_index":(f.get("state") or {}).get("current_index") if row else a.get("final_index"),
        "pending_exports":len(f.get("pending_exports") or []),
        "config_hash":s(f.get("config_hash") or a.get("config_hash")),
        "firestore_config_hash":s(f.get("config_hash")),
        "archive_config_hash":s(a.get("config_hash")),
        "provenance_hash":s(f.get("provenance_hash")),
        "archive_provenance_hash": (hashlib.sha256(json.dumps(a["provenance"], sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest() if a.get("provenance") is not None else ""),
        "archive_checksum_valid": (hashlib.sha256(json.dumps({k:v for k,v in a.items() if k!="content_sha256"}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest() == a["content_sha256"] if a.get("content_sha256") else None),
        "created_at":s(f.get("created_at")),"updated_at":s(f.get("updated_at")),
        "firestore_pid":s(prolific_f.get("prolific_pid")).lower(),
        "archive_pid":s(prolific_a.get("prolific_pid")).lower(),
        "firestore_campaign":s(prolific_f.get("prolific_study_id")),
        "archive_campaign":s(prolific_a.get("prolific_study_id")),
        "firestore_policy":s(f.get("policy")),"archive_policy":s(a.get("policy")),
        "state_session_id":s(f.get("session_id")),
    }


def _atomic_private_csv(path:Path,rows,fieldnames):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8",newline="") as fh:
        os.chmod(path,0o600)
        writer=csv.DictWriter(fh,fieldnames=fieldnames,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _safe_json(path,data):
    with path.open("x",encoding="utf-8") as fh:
        os.chmod(path,0o600)
        json.dump(data,fh,indent=2,sort_keys=True)
        fh.write("\n")


def audit(rosters, firestore_docs, finals, discover_mode):
    fs={(d["study"],d["sid"]):d for d in firestore_docs}
    records=[parse_record(fs.get(k),finals.get(k)) for k in sorted(set(fs)|set(finals))]
    issues=[]
    def flag(code,r,message):
        issues.append({"code":code,"study_id":r.get("study_id", ""),
                       "prolific_study_id":r.get("prolific_study_id", ""),
                       "prolific_pid":r.get("prolific_pid", ""),
                       "dtag_session_id":r.get("dtag_session_id", ""),
                       "detail":message})
    roster_owners=defaultdict(set)
    for cid,roster in rosters.items():
        for pid in roster["pids"]:
            roster_owners[pid].add(cid)
    for pid,cids in roster_owners.items():
        if len(cids)>1:
            flag("APPROVED_PID_IN_MULTIPLE_PDFS", {"prolific_pid":pid}, "Roster PID appears in multiple paid summaries")
    pids=defaultdict(list)
    for r in records:
        pid=r["prolific_pid"]
        if r["consented"] and pid:
            pids[pid].append(r)
        if r["consented"] and not pid:
            flag("CONSENTED_PID_MISSING",r,"No Prolific PID stored for consented participant")
        if r["consented"] and not r["prolific_study_id"]:
            flag("CONSENTED_CAMPAIGN_MISSING",r,"No Prolific STUDY_ID stored")
        if r["firestore_present"] and r["state_session_id"] and r["state_session_id"]!=r["dtag_session_id"]:
            flag("SESSION_ID_MISMATCH",r,"Stored session ID differs from Firestore document ID")
        if r["gcs_final_present"] and not r["consented"]:
            flag("ARCHIVED_UNCONSENTED",r,"GCS final archive exists but Firestore consent is not accepted")
        if r["firestore_config_hash"] and r["archive_config_hash"] and r["firestore_config_hash"] != r["archive_config_hash"]:
            flag("GCS_CONFIG_HASH_MISMATCH",r,"Firestore config hash differs from archived configuration")
        if r["archive_checksum_valid"] is False:
            flag("GCS_ARCHIVE_CHECKSUM_MISMATCH",r,"GCS final.json self-checksum fails")
        if r["provenance_hash"] and r["archive_provenance_hash"] and r["provenance_hash"] != r["archive_provenance_hash"]:
            flag("GCS_MODEL_PROVENANCE_MISMATCH",r,"Model provenance hash differs between Firestore and GCS")
        if r["firestore_pid"] and r["archive_pid"] and r["firestore_pid"] != r["archive_pid"]:
            flag("GCS_PID_MISMATCH",r,"Participant identifier disagrees across Firestore and GCS")
        if r["firestore_campaign"] and r["archive_campaign"] and r["firestore_campaign"]!=r["archive_campaign"]:
            flag("GCS_CAMPAIGN_MISMATCH",r,"Prolific STUDY_ID disagrees across Firestore and GCS")
        if r["firestore_policy"] and r["archive_policy"] and r["firestore_policy"]!=r["archive_policy"]:
            flag("GCS_POLICY_MISMATCH",r,"Intervention policy disagrees across Firestore and GCS")
        expected=STUDY_CONFIGS.get(r["study_id"],{}).get("expected_policy")
        if r["consented"] and r["policy"] and expected not in (None,"randomized") and r["policy"]!=expected:
            flag("STUDY_POLICY_MISMATCH",r,f"Study requires {expected}, observed {r['policy']}")
        declared=CAMPAIGNS.get(r["prolific_study_id"])
        if declared and r["consented"]:
            if r["study_id"]!=declared["study"]:
                flag("KNOWN_CAMPAIGN_WRONG_STUDY",r,"Participant filed under different DTAG study than campaign map")
            if r["policy"] and r["policy"]!=declared["policy"]:
                flag("KNOWN_CAMPAIGN_WRONG_PUSH",r,"Observed policy does not match right-push campaign")
        if r["adaptive_count_firestore"] is not None and not 0 <= r["adaptive_count_firestore"] <= 20 and r["consented"]:
            flag("INVALID_PROGRESS",r,"Adaptive answer count outside 0..20")
        if r["adaptive_count_firestore"] is not None and r["adaptive_count_archive"] is not None and r["adaptive_count_firestore"] != r["adaptive_count_archive"]:
            flag("PROGRESS_ARCHIVE_MISMATCH",r,"Firestore adaptive answer count differs from GCS final")
        if r["phase"]=="complete" and r["study_id"] in STUDY_CONFIGS and r["adaptive_count_firestore"]!=20:
            flag("COMPLETE_WITHOUT_20",r,"Phase complete but Firestore does not record 20 adaptive answers")
        if r["phase"]=="complete" and not r["gcs_final_present"]:
            flag("COMPLETE_NO_GCS_FINAL",r,"Completed Firestore session lacks final.json")
        if r["gcs_final_present"] and r["study_id"] in STUDY_CONFIGS and r["adaptive_count_archive"] != 20:
            flag("ARCHIVE_FINAL_NOT_20",r,"GCS final.json does not contain 20 intervention answers")
        if r["gcs_final_present"] and not r["firestore_present"]:
            flag("ARCHIVE_ONLY_SESSION",r,"GCS completed archive exists without corresponding Firestore session")
        if r["pending_exports"]:
            flag("PENDING_GCS_EXPORTS",r,"Firestore session still has pending archive exports")
    for pid,rr in pids.items():
        if len(rr)>1:
            for r in rr:
                flag("MULTIPLE_CONSENTED_SESSIONS_SAME_PID",r,f"PID has {len(rr)} consented session records across studies/campaigns")
        if len({r["prolific_study_id"] for r in rr})>1:
            for r in rr:
                flag("PID_IN_MULTIPLE_STORED_CAMPAIGNS",r,"Participant appears under multiple Prolific STUDY_ID values")
    # Participant-specific roster crosswalk; no heuristic ID matching.
    roster_rows=[]
    for cid,roster in rosters.items():
        meta=CAMPAIGNS[cid]
        matching=[r for r in records if r["consented"] and r["prolific_study_id"]==cid and r["study_id"]==meta["study"]]
        matched_pids={r["prolific_pid"] for r in matching}
        for pid in sorted(roster["pids"]):
            same=[r for r in matching if r["prolific_pid"]==pid]
            elsewhere=[r for r in records if r["prolific_pid"]==pid and r not in same]
            full=[r for r in same if r["adaptive_count_firestore"]==20 or r["adaptive_count_archive"]==20]
            final=[r for r in same if r["gcs_final_present"] and r["adaptive_count_archive"]==20]
            policies=sorted({r["policy"] for r in same if r["policy"]})
            if not same:
                flag("PAID_PID_NOT_IN_EXPECTED_DTAGS",{"study_id":meta["study"],"prolific_study_id":cid,"prolific_pid":pid},
                     "Approved Prolific PID has no consented DTAG session under expected study+campaign")
            if elsewhere:
                flag("PAID_PID_STORED_ELSEWHERE",{"study_id":meta["study"],"prolific_study_id":cid,"prolific_pid":pid},
                     "Approved PID also appears under other DTAG study/campaign or unconsented session")
            if same and len(same)>1:
                flag("PAID_PID_MULTIPLE_MATCHING_SESSIONS",same[0],"Approved PID matches multiple DTAG session IDs")
            if same and not full:
                flag("PAID_PID_NOT_20_ANSWERS",same[0],"Paid participant has no verified 20-question DTAG trajectory")
            if same and not final:
                flag("PAID_PID_NO_COMPLETE_GCS_ARCHIVE",same[0],"Paid participant lacks GCS final with 20 adaptive answers")
            if same and policies != [meta["policy"]]:
                flag("PAID_PID_PUSH_NOT_RIGHT",same[0],"Paid participant's observed push is not exclusively right")
            roster_rows.append({
                "pdf_summary_id":roster["summary_id"],"expected_campaign_id":cid,
                "expected_study_id":meta["study"],"recruitment":meta["short"],
                "prolific_pid":pid,"matching_consent_sessions":len(same),
                "dtag_session_ids":";".join(sorted(x["dtag_session_id"] for x in same)),
                "observed_policies":";".join(policies),
                "max_adaptive_questions":max([x["adaptive_count_firestore"] or 0 for x in same]+[x["adaptive_count_archive"] or 0 for x in same]+[0]),
                "verified_final_archives":len(final),
                "matching_id_and_campaign":bool(same),
                "other_dtag_session_count":len(elsewhere),
            })
        unrelated=[r for r in matching if r["prolific_pid"] not in roster["pids"]]
        for r in unrelated:
            flag("DTAG_PID_NOT_APPROVED_IN_PDF",r,"Consented DTAG session has correct campaign but PID not among 15 approved in Prolific payment PDF; could be returned/incomplete/replacement")
    # Compare immutable scientific configuration across participants within each campaign
    # and across the two new campaign waves; different hashes may indicate version drift.
    for cid,meta in CAMPAIGNS.items():
        rr=[r for r in records if r["consented"] and r["study_id"]==meta["study"]
            and r["prolific_study_id"]==cid]
        hashes={r["config_hash"] for r in rr if r["config_hash"]}
        if len(hashes)>1:
            flag("MIXED_CONFIG_HASH_WITHIN_CAMPAIGN", {"study_id":meta["study"], "prolific_study_id":cid},
                 f"Campaign has {len(hashes)} distinct scientific config hashes")
    campaigns=list(CAMPAIGNS)
    configs=[]
    for cid in campaigns:
        configs.append({r["config_hash"] for r in records if r["consented"] and
            r["prolific_study_id"]==cid and r["config_hash"]})
    if all(configs) and configs[0]!=configs[1]:
        flag("CROSS_CAMPAIGN_CONFIG_HASH_DIFFERENCE",{"study_id":CAMPAIGNS[campaigns[0]]["study"]},
             "Democratic and Republican cohorts used different observed config hash sets")
    # Entire database grouping, not only manuscript completers.
    studies=defaultdict(list)
    groups=defaultdict(list)
    for r in records:
        studies[r["study_id"]].append(r)
        groups[(r["study_id"],r["prolific_study_id"] or "(missing)",r["policy"] or "(unset)")].append(r)
    for sid in STUDY_CONFIGS:
        studies.setdefault(sid,[])
    for cid,meta in CAMPAIGNS.items():
        groups.setdefault((meta["study"],cid,meta["policy"]),[])
    def counts(rr):
        consent=[r for r in rr if r["consented"]]
        pidset={r["prolific_pid"] for r in consent if r["prolific_pid"]}
        completed=[r for r in consent if r["adaptive_count_firestore"]==20 or r["adaptive_count_archive"]==20]
        finalized=[r for r in consent if r["gcs_final_present"] and r["adaptive_count_archive"]==20]
        return {"sessions_total":len(rr),"consented_sessions":len(consent),"unique_consented_pids":len(pidset),
           "started_sessions":sum(r["baseline_index"] is not None for r in consent),
           "all_gcs_final_sessions":sum(r["gcs_final_present"] for r in rr),
           "archived_adaptive_answer_counts":json.dumps(dict(sorted(Counter(
                r["adaptive_count_archive"] for r in rr if r["gcs_final_present"]
                and r["adaptive_count_archive"] is not None).items()))),
           "completed_20_sessions":len(completed),
           "unique_completed_20_pids":len({r["prolific_pid"] for r in completed if r["prolific_pid"]}),
           "gcs_final_20_sessions":len(finalized),
           "unique_gcs_final_20_pids":len({r["prolific_pid"] for r in finalized if r["prolific_pid"]}),
           "not_complete_sessions":len(consent)-len(completed),
           "missing_consent_pid":sum(not r["prolific_pid"] for r in consent),
           "distinct_config_hashes":len({r["config_hash"] for r in consent if r["config_hash"]}),
           "earliest_created":min([r["created_at"] for r in rr if r["created_at"]],default=""),
           "latest_updated":max([r["updated_at"] for r in rr if r["updated_at"]],default="")}
    study_table=[]
    for sid,rr in sorted(studies.items()):
        cfg=STUDY_CONFIGS.get(sid,{})
        study_table.append({"study_id":sid,"study_name":cfg.get("label","UNCLASSIFIED — inspect/test?"),
          "baseline_question_count":cfg.get("baseline","UNKNOWN"),
          "expected_policy":cfg.get("expected_policy","UNKNOWN"),
          "observed_policy_distribution":json.dumps(dict(sorted(Counter(r["policy"] or "(unset)" for r in rr if r["consented"]).items()))),
          "observed_prolific_campaign_ids":";".join(sorted({r["prolific_study_id"] for r in rr if r["prolific_study_id"]})),
          **counts(rr)})
    cohort_table=[]
    for (sid,cid,arm),rr in sorted(groups.items()):
        meta=CAMPAIGNS.get(cid,{})
        cohort_table.append({"study_id":sid,"prolific_study_id":cid,"recruitment_label":meta.get("name","Unknown — verify Prolific campaign"),
             "arm":arm,"declared_planned_slots":meta.get("planned_slots",""),**counts(rr)})
    roster_table=[]
    for cid,roster in rosters.items():
        rr=[r for r in roster_rows if r["expected_campaign_id"]==cid]
        roster_table.append({"prolific_campaign_id_declared":cid,
          "pdf_study_title":roster["pdf_title"],"prolific_summary_id":roster["summary_id"],
          "approved_unique_pids":len(roster["pids"]),"dtag_pids_linked":sum(r["matching_id_and_campaign"] for r in rr),
          "linked_20_answers":sum(r["max_adaptive_questions"]==20 for r in rr),
          "linked_archived_final_20":sum(r["verified_final_archives"]>0 for r in rr),
          "approved_pids_with_other_sessions":sum(r["other_dtag_session_count"]>0 for r in rr),
          "paid_without_exact_dtag_link":sum(not r["matching_id_and_campaign"] for r in rr)})
    return {"records":records,"crosswalk":roster_rows,"issues":issues,"studies":study_table,
            "cohorts":cohort_table,"rosters":roster_table,"scan_mode":discover_mode,
            "counts":{"firestore_session_records":len(fs),"gcs_final_json":len(finals),
                      "distinct_dtag_studies":len(studies),
                      "unique_consented_prolific_ids_all_studies":len(pids)}}


def write_outputs(out, report):
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    os.chmod(out,0o700)
    tables={
       "all_studies.csv":report["studies"],
       "all_cohorts_by_campaign_and_arm.csv":report["cohorts"],
       "latest_pdf_roster_reconciliation.csv":report["rosters"],
       "PRIVATE_participant_crosswalk.csv":report["crosswalk"],
       "PRIVATE_all_sessions.csv":report["records"],
       "PRIVATE_issues.csv":report["issues"],
    }
    for filename,rr in tables.items():
        if rr:
            _atomic_private_csv(out/filename,rr,list(rr[0].keys()))
        else:
            _atomic_private_csv(out/filename,[],["no_rows"])
    _safe_json(out/"summary.json",{
       "generated_utc":datetime.now(timezone.utc).isoformat(),
       "counts":report["counts"],"scan_mode":report["scan_mode"],
       "studies":report["studies"],"cohorts":report["cohorts"],"paid_rosters":report["rosters"],
       "issue_type_counts":dict(sorted(Counter(r["code"] for r in report["issues"]).items())),
       "caveats":["Prolific PDFs show approved paid participants only, not rejected/returned/incomplete submissions.",
          "The PDF does not print the Prolific STUDY_ID; mapping is investigator-declared until validated by matched Firestore PIDs.",
          "A saved DTAG session is not necessarily a distinct Prolific participant.",
          "A Firestore complete phase plus GCS final.json with 20 answers constitutes a stronger archival completion check than session count alone.",
          "Some dynamically discovered staging/test studies have unknown calibration lengths.",
          "This audit does not establish a change in human belief; it audits recorded model-inferred trajectories."],
    })
    print("\nSTUDY INVENTORY (all discovered studies, not just 20/20 completers)")
    print(f"{'DTAG STUDY':43} {'SESS':>5} {'PID':>5} {'20/20':>5} {'GCS':>5} {'ARM'}")
    for x in report["studies"]:
        print(f"{x['study_id'][:43]:43} {x['sessions_total']:>5} {x['unique_consented_pids']:>5} {x['completed_20_sessions']:>5} {x['gcs_final_20_sessions']:>5} {x['observed_policy_distribution']}")
    print("\nPROLIFIC APPROVED-PAYMENT ROSTER RECONCILIATION")
    for x in report["rosters"]:
        print(f"{x['pdf_study_title']}: approved={x['approved_unique_pids']}, matched to correct study+campaign={x['dtag_pids_linked']}, 20-answer={x['linked_20_answers']}, GCS final 20={x['linked_archived_final_20']}, unmatched={x['paid_without_exact_dtag_link']}")
    print("\nISSUES:",dict(sorted(Counter(r["code"] for r in report["issues"]).items())))
    print("Firestore scan:",report["scan_mode"])
    print("Private output (mode 0700):",out)
    print("CAUTION: PRIVATE_*.csv contain Prolific participant IDs. Never commit/share them publicly.")


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dem-pdf",required=True,type=Path,help="Original Prolific payment summary PDF, DTAG_right_DEM")
    ap.add_argument("--rep-pdf",required=True,type=Path,help="Original Prolific payment summary PDF, DTAG_right_REP")
    ap.add_argument("--project",default="pkcsaas-01")
    ap.add_argument("--database",default="dtag-human-pilot")
    ap.add_argument("--bucket",default="pkcsaas-01-dtag-study-data")
    ap.add_argument("--out",type=Path,required=True,help="New private results directory; must not already exist")
    ap.add_argument("--skip-gcs",action="store_true",help="Faster diagnostic; disables archive verification and sets no archive flags")
    ap.add_argument("--offline",type=Path,help="Developer fixture JSON with {'firestore_docs':[],'finals':[]} instead of reading GCP")
    ap.add_argument("--strict",action="store_true",help="Exit nonzero if any paid PID is missing or has wrong push; files still written")
    args=ap.parse_args()
    if args.out.exists():
        ap.error(f"Output path already exists (refusing overwrite): {args.out}")
    if Path.cwd().resolve() != Path("/") and args.out.resolve().is_relative_to(Path.cwd().resolve()):
        print("WARNING: output directory is inside your working tree: use /private or /tmp and NEVER git add it",file=sys.stderr)
    rosters={}
    for cid,meta in CAMPAIGNS.items():
        pdf=args.dem_pdf if meta["short"]=="DEM" else args.rep_pdf
        rosters[cid]=extract_pdf(pdf,meta["pdf_title"])
    overlap=set.intersection(*(set(v["pids"]) for v in rosters.values()))
    print("PDF-only verification (not yet matched to GCP):", " / ".join(f"{CAMPAIGNS[cid]['short']}: {len(r['pids'])} unique approved" for cid,r in rosters.items()), f"; cross-roster overlap={len(overlap)}")
    if overlap:
        raise SystemExit("STOP: PDFs share Prolific participant IDs")
    if args.offline:
        fixture=json.loads(args.offline.read_text())
        firestore_docs=fixture.get("firestore_docs",[])
        finals={(x["study_id"],x["session_id"]):x for x in fixture.get("finals",[])}
        discover_mode="OFFLINE_FIXTURE"
    else:
        bearer=gcloud_token()
        discovered=set(STUDY_CONFIGS)
        if not args.skip_gcs:
            print("Discovering all GCS study namespaces...",file=sys.stderr)
            discovered |= gcs_discover_studies(args.bucket,bearer)
        try:
            print("Scanning Firestore collection-group 'sessions'...",file=sys.stderr)
            firestore_docs=scan_collection_group(args.project,args.database,bearer)
            discover_mode="FULL_COLLECTION_GROUP"
        except Exception as exc:
            print(f"WARNING: global collection-group scan failed ({exc}); using listed study IDs.",file=sys.stderr)
            discover_mode="KNOWN_AND_GCS_DISCOVERED_STUDIES_ONLY"
            firestore_docs=[]
            for study in sorted(discovered):
                print(f"  Firestore {study}",file=sys.stderr)
                firestore_docs += scan_one_study(args.project,args.database,study,bearer)
        discovered |= {d["study"] for d in firestore_docs}
        finals=read_gcs_finals(args.bucket,discovered,bearer) if not args.skip_gcs else {}
    report=audit(rosters,firestore_docs,finals,discover_mode)
    if args.skip_gcs:
        # Do not call an unverified final archive 'missing' when checks were skipped.
        report["issues"]=[i for i in report["issues"] if i["code"] not in ("COMPLETE_NO_GCS_FINAL","PAID_PID_NO_COMPLETE_GCS_ARCHIVE")]
        for x in report["rosters"]:
            x["linked_archived_final_20"]="NOT_CHECKED"
    if discover_mode!="FULL_COLLECTION_GROUP" and discover_mode!="OFFLINE_FIXTURE":
        report["issues"].append({"code":"FIRESTORE_SCAN_NOT_EXHAUSTIVE","study_id":"","prolific_study_id":"","prolific_pid":"","dtag_session_id":"",
        "detail":"Collection-group scan failed; study enumeration may omit never-finalized studies without known IDs"})
    write_outputs(args.out,report)
    critical={"PAID_PID_NOT_IN_EXPECTED_DTAGS","PAID_PID_PUSH_NOT_RIGHT","KNOWN_CAMPAIGN_WRONG_PUSH","GCS_PID_MISMATCH","GCS_CAMPAIGN_MISMATCH"}
    return 2 if args.strict and any(i["code"] in critical for i in report["issues"]) else 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (ValueError,RuntimeError) as exc:
        raise SystemExit("AUDIT FAILED: " + str(exc)) from exc