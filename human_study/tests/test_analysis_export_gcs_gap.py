"""Regression tests for Firestore-only, unarchived completed study sessions.

The session remains visible in private inventory but must not create a
synthetic step-zero trajectory or be treated as an archived 20/20 completion.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The researcher-only CLI lives in human_study/scripts, outside the backend package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from export_dtag_analysis_data import produce, sha256


STUDY = "prolific-v3-human-opinions-2026-10"
SID = "b" * 32
KEY = b"x" * 32


def session_row():
    return {
        "study_id": STUDY,
        "dtag_session_id": SID,
        "policy": "left",
        "phase": "complete",
        "consented": "True",
        "adaptive_count_firestore": "20",
        "baseline_index": "-0.3",
    }


def test_firestore_complete_without_gcs_archive_is_not_trajectory():
    rows, counts, failed = produce(
        [session_row()], set(), {},
        getter=lambda uri: (_ for _ in ()).throw(AssertionError(uri)),
        key=KEY,
    )
    assert not failed
    assert counts["sessions"] == 1
    assert counts["complete_20_archive"] == 0
    assert rows["steps.csv"] == []
    assert rows["questions.csv"] == []
    assert rows["sessions.csv"][0]["firestore_phase"] == "complete"
    assert rows["sessions.csv"][0]["source_class"] == "no_archive"
    assert rows["sessions.csv"][0]["baseline_index"] == -0.3
    codes = {r["code"] for r in rows["flags.csv"]}
    assert "FIRESTORE_COMPLETE_NO_GCS_FINAL" in codes
    assert "FIRESTORE_ANSWERS_NOT_RECOVERED" in codes


def test_partial_archived_question_does_retain_observed_trajectory():
    question = {
        "status": "answered",
        "phase": "intervention",
        "question_id": "q1",
        "ordinal": 1,
        "step": 0,
        "target_variable": "var1",
        "response_value": "yes",
        "index_result": {
            "index_before": -0.3,
            "index_after": -0.2,
            "observed_conditional_index_delta": 0.1,
        },
    }
    name = f"studies/{STUDY}/sessions/{SID}/questions/q1.json"
    payload = {"question": question}
    payload["content_sha256"] = sha256(payload)
    rows, counts, failed = produce(
        [session_row()], set(), {(STUDY, SID): {"questions/q1.json": name}},
        getter=lambda uri: payload if uri == name else (_ for _ in ()).throw(AssertionError(uri)),
        key=KEY,
    )
    assert not failed
    assert counts["complete_20_archive"] == 0
    assert len(rows["steps.csv"]) == 2
    assert [r["step"] for r in rows["steps.csv"]] == [0, 1]
    assert rows["sessions.csv"][0]["source_class"] == "partial"
    codes = {r["code"] for r in rows["flags.csv"]}
    assert "FIRESTORE_COMPLETE_NO_GCS_FINAL" in codes
    assert "FIRESTORE_ANSWERS_NOT_RECOVERED" not in codes
