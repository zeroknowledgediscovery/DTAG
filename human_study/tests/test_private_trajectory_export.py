"""Regression checks for the private, postprocessable trajectory export.

Synthetic data only: no participant identifiers or experimental records.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"export_private_trajectories.py"
SPEC=importlib.util.spec_from_file_location("private_trajectory_export", SCRIPT)
MODULE=importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fixture(tmp_path):
    source=tmp_path/"private-analysis"
    source.mkdir()
    (source/"manifest.json").write_text(json.dumps({"schema_version":1})+"\n")
    cases=[
        ("sleft", "prolific-v3-left-followup-2026-10", "left", -.2, -.1),
        ("sright", "prolific-v3-right-followup-2026-10", "right", -.2, -.005),
        ("snocal", "dtag-v3-nocal-right-2026-10", "right", 0.0, .01),
    ]
    sessions,steps=[],[]
    for uid,study,arm,i0,delta in cases:
        calibrated = "nocal" not in study
        proto="six_question_calibration" if calibrated else "zero_calibration"
        vals=[i0+delta*t for t in range(21)]
        sessions.append({
            "session_uid":uid,"participant_uid":"p"+uid,
            "dtag_study_id":study,"prolific_campaign_id":"campaign",
            "recruitment_cohort":"synthetic","protocol":proto,
            "policy":arm,"source_class":"final",
            "complete_20_archive":"True","observed_adaptive_steps":"20",
            "baseline_index":i0,"final_archived_index":vals[-1]})
        for step,v in enumerate(vals):
            steps.append({"session_uid":uid,"step":str(step),
                "source_class":"final","index":v,
                "index_before":vals[step-1] if step else "",
                "observed_step_delta":delta if step else "",
                "predicted_target_only_delta":"","accepted_assignment_count":"1",
                "observed_scope":"","predicted_scope":""})
    write_csv(source/"sessions.csv",sessions[0],sessions)
    write_csv(source/"steps.csv",steps[0],steps)
    return source


def test_full_trajectories_are_private_and_q4_scored(tmp_path):
    source=fixture(tmp_path)
    dest=tmp_path/"private-traj"
    MODULE.export(source,dest,expect_complete=3)
    with (dest/"trajectories_wide_PRIVATE.csv").open() as f:
        rows={r["session_uid"]:r for r in csv.DictReader(f)}
    assert len(rows)==3
    assert len([k for k in rows["sleft"] if k.startswith("i") and k[1:].isdigit()])==21
    assert rows["sright"]["q4_resistance_flag"]=="True"
    assert rows["sright"]["endpoint_correct_resistance"]=="True"
    assert rows["sright"]["endpoint_extended_success"]=="True"
    assert rows["snocal"]["initial_ideology"]=="empty_state_not_human_phenotype"
    assert rows["snocal"]["q4_resistance_flag"]==""
    with (dest/"trajectories_long_PRIVATE.csv").open() as f:
        assert len(list(csv.DictReader(f)))==63
    with (dest/"trajectory_manifest_PRIVATE.json").open() as f:
        manifest=json.load(f)
    assert manifest["records"]["wide"]==3
    assert manifest["records"]["long"]==63
    assert "trajectories_wide_PRIVATE.csv" in manifest["files_sha256"]
    assert (dest.stat().st_mode & 0o077)==0


def test_refuses_existing_destination_without_modifying(tmp_path):
    source=fixture(tmp_path)
    dest=tmp_path/"output"
    dest.mkdir()
    with pytest.raises(ValueError,match="refusing overwrite"):
        MODULE.export(source,dest)


def test_abort_if_completed_count_not_expected(tmp_path):
    source=fixture(tmp_path)
    dest=tmp_path/"output"
    with pytest.raises(ValueError,match="Expected 102"):
        MODULE.export(source,dest,expect_complete=102)
    assert not dest.exists()
