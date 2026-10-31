"""Synthetic end-to-end tests; no Prolific identifiers or human records."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_nhb_explanations as nhb


def csv_write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_synthetic(root):
    root.mkdir()
    sessions, steps, questions, assignments = [], [], [], []
    groups = [
        ("left", -0.2, -.01, -.04, 16),
        ("left", -0.2, .01, +.01, 1),
        ("left", +0.2, -.01, -.04, 4),
        ("right", -0.2, -.01, -.04, 17),  # Q4 TP
        ("right", -0.2, -.01, +.04, 2),   # Q4 FP
        ("right", -0.2, +.01, +.04, 10),  # Q4 TN
        ("right", +0.2, +.01, +.04, 9),   # initially Right
        ("neutral", -0.2, 0, 0, 6),
        ("neutral", +0.2, 0, 0, 1),
        ("random", -0.2, 0, 0, 2),
        ("random", +0.2, 0, 0, 3),
    ]
    i = 0
    for policy, base, q4, final, n in groups:
        for _ in range(n):
            uid = f"synthetic{i:03d}"
            i += 1
            # Exercise study-wave stratification without changing policy counts.
            study = ("prolific-v3-left-followup-2026-10" if policy == "left"
                     else "prolific-v3-right-followup-2026-10" if policy == "right"
                     else "prolific-v3-human-opinions-2026-10")
            x = {t: base + q4 * min(t, 4) / 4
                 + (final-q4) * max(t-4, 0) / 16 for t in range(21)}
            sessions.append(dict(session_uid=uid, dtag_study_id=study,
                                 protocol="six_question_calibration",
                                 policy=policy, complete_20_archive="true",
                                 baseline_index=x[0], final_archived_index=x[20]))
            for t in range(21):
                quid = f"{uid}-q{t}"
                steps.append(dict(session_uid=uid, step=t, index=x[t],
                                  source_question_uid=quid if t else "",
                                  observed_step_delta=x[t]-x[t-1] if t else "",
                                  predicted_target_only_delta=0.005 if t else "",
                                  predicted_scope="target_only",
                                  observed_scope="accepted_assignments"))
                if t == 0:
                    continue
                var = "colath" if t % 2 == 0 else "natchld"
                multi = (t % 3 == 0)
                questions.append(dict(session_uid=uid, phase="intervention",
                                      adaptive_step=t, question_uid=quid,
                                      target_variable=var, index_before=x[t-1],
                                      index_after=x[t], accepted_assignment_count=2 if multi else 1,
                                      predicted_target_only_delta=0.005,
                                      predicted_scope="target_only", observed_scope="accepted_assignments"))
                assignments.append(dict(session_uid=uid, phase="intervention",
                                        question_uid=quid, mapped_variable=var,
                                        native_value="yes", assignment_type="explicit_multi_variable"))
                if multi:
                    assignments.append(dict(session_uid=uid, phase="intervention",
                                            question_uid=quid, mapped_variable="relpersn",
                                            native_value="no", assignment_type="explicit_multi_variable"))
    assert i == 71
    for fname, rows in [("sessions.csv", sessions), ("steps.csv", steps),
                        ("questions.csv", questions), ("assignments.csv", assignments)]:
        csv_write(root / fname, rows)
    return i


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_end_to_end_release_and_privacy(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    public = checkout / "tex" / "Figures" / "nhb_explanatory"
    monkeypatch.setattr(nhb, "ROOT", checkout)
    monkeypatch.setattr(nhb, "PUBLIC", public)
    analysis = tmp_path / "private_input"
    make_synthetic(analysis)
    gss = tmp_path / "gss_map.csv"
    csv_write(gss, [
        dict(variable="colath", question_text="Allow anti-religious teacher", question_text_filled=""),
        dict(variable="natchld", question_text="Spending on childcare", question_text_filled=""),
        dict(variable="relpersn", question_text="Religious person", question_text_filled=""),
    ])
    private = tmp_path / "private_results"
    manifest = nhb.run(analysis, private, public, gss,
                       expected=71, boots=100, seed=123)
    assert manifest["n_sessions"] == 71
    assert manifest["n_events"] == 1420
    assert manifest["q4_confusion"] == {"TP":17, "FP":2, "FN":0, "TN":10}
    assert manifest["prediction_available"] == 1420
    assert manifest["prediction_target_aligned"] < 1420
    stages = read(public / "nhb_resistance_stage_metrics.csv")
    by = {(r["group"],r["stage"]):r for r in stages}
    assert int(by[("right_initially_left_q4_flagged","late")]["n_sessions"]) == 19
    assert int(by[("right_initially_left_q4_unflagged","late")]["n_sessions"]) == 10
    assert int(by[("right_initially_right","late")]["n_sessions"]) == 9
    assert int(by[("right_all","all")]["n_sessions"]) == 38
    assert int(by[("left_all","all")]["n_sessions"]) == 21
    assert abs(float(by[("right_initially_left_q4_flagged","early")]
                     ["mean_signed_displacement"]) + .01) < 1e-9
    assert read(public / "nhb_right_q4_trajectories.csv")
    assert read(public / "nhb_predicted_observed_quintiles.csv")
    assert read(public / "nhb_question_topics.csv")
    assert read(public / "nhb_target_questions.csv")
    assert read(private / "mapped_native_answers_PRIVATE.csv")
    assert read(public / "nhb_curated_answer_categories.csv") == []
    assert any(r["native_value"] == "yes"
               for r in read(private / "mapped_native_answers_PRIVATE.csv"))
    # Public files cannot contain participant pseudonyms, response values, or raw text.
    for path in public.glob("*.csv"):
        text = path.read_text()
        assert "synthetic000" not in text
        assert "native_value" not in text
        assert ",yes," not in text
    with pytest.raises(ValueError, match="outside"):
        nhb.run(analysis, checkout/"bad_private", public, gss, expected=71, boots=100)


def test_curated_answers_only_with_reviewed_allowlist(tmp_path):
    rows = [dict(group="right_all", stage="late",
                 target_variable="colath", mapped_variable="colath",
                 native_value="yes", n_sessions=9, n_event_associations=10,
                 sum_associated_signed=0.2, sum_associated_positive=0.3,
                 n_multi_assignment=2),
            dict(group="right_initially_left_q4_flagged",stage="late",
                 target_variable="colath", mapped_variable="colath",
                 native_value="yes", n_sessions=15, n_event_associations=16,
                 sum_associated_signed=0.3, sum_associated_positive=0.3,
                 n_multi_assignment=2),
            dict(group="left_all",stage="early",
                 target_variable="natchld", mapped_variable="natchld",
                 native_value="no", n_sessions=3, n_event_associations=5,
                 sum_associated_signed=0.1, sum_associated_positive=0.2,
                 n_multi_assignment=0)]
    allow = tmp_path / "allow.csv"
    csv_write(allow, [
        dict(mapped_variable="colath",native_value="yes",public_label="Allows teaching"),
        dict(mapped_variable="natchld",native_value="no",public_label="Less spending")])
    answer = nhb.curated_answers(rows, allow)
    assert len(answer) == 1
    assert answer[0]["curated_category"] == "Allows teaching"
    assert "native_value" not in answer[0]


def test_topic_suppresses_small_cells_and_bootstrap_mean():
    events = [dict(session_uid=f"s{i}",topic="religion_culture",
                   target="religinf",step=5,signed=0.01,
                   positive_gain=0.01,n_assignments=1)
              for i in range(1,5)]
    gp = {"right_initially_left_q4_flagged":[f"s{i}" for i in range(1,5)],
          "right_initially_left_q4_unflagged":[],
          "right_initially_right":[], "right_all":[], "left_all":[]}
    public = nhb.topic_records(events, gp, public=True)
    assert public == []
    assert nhb.bootstrap_person_mean([1, 1, 1], seed=17, boots=100) == (1, 1, 1)
