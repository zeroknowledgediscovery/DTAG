"""Zero-calibration fixed-arm Prolific study regression tests.

Exercises the real V3 service lifecycle using synthetic geometry and
recorded answers; does not access GCS, Firestore, OpenAI, or Prolific.
"""
from __future__ import annotations

import json

import pytest

from human_study.service import StudyService
from human_study.storage import MemoryRepository, MemoryArchive
from human_study.study_config import StudyConfig, AttentionCheck
from test_native_webapp_service import NativeFixtureAdapter, RecordedAnswerLLM
from human_study.multi_observations import replay


@pytest.mark.parametrize("arm", ["left", "right"])
def test_zero_baseline_starts_adaptive_immediately_and_finishes(instrument, adapter, arm):
    baseline_defs = instrument.bank("baseline")[:4]
    config = StudyConfig(
        study_id=f"test-nocal-{arm}",
        question_mode="llm_required",
        response_mode="free_text_multi",
        candidate_mode="native_webapp",
        push_response_mode="draw",
        fixed_arm=arm,
        initial_steps=0,
        intervention_steps=3,
        items=baseline_defs,
        excluded_ids=tuple(i.item_id for i in baseline_defs),
    )
    native = NativeFixtureAdapter(adapter)
    archive = MemoryArchive()
    repo = MemoryRepository()
    svc = StudyService(config, native, RecordedAnswerLLM(), repo, archive)

    opened = svc.start()
    sid = opened["session_id"]
    view = svc.consent(sid, True, opened["session_version"])

    assert config.bank("baseline") == []
    assert view["phase"] == "intervention"
    assert view["progress"] == {"completed": 0, "total": 3}
    assert view["question"] is not None
    assigned = repo.read(sid).session
    assert assigned["policy"] == arm
    assert assigned["state"]["initial_observed_state"] == {}
    assert assigned["state"]["baseline_index"] == pytest.approx(native.index({}))

    for step in range(3):
        assert view["phase"] == "intervention"
        qid = view["question"]["question_id"]
        question = repo.read(sid).records[f"questions/{qid}"]
        assert question["target_variable"] not in set(config.excluded_ids)
        view = svc.answer(sid, {
            "question_id": qid,
            "answer_value": None,
            "text_answer": "yes, with additional reasons",
            "missing_reason": None,
            "idempotency_key": f"no-calibration-{arm}-{step}",
            "expected_session_version": view["session_version"],
        })["current"]

    assert view["phase"] == "ready_to_complete"
    result = svc.complete(sid)
    assert result["phase"] == "complete"
    final = json.loads(archive.objects[
        f"studies/{config.study_id}/sessions/{sid}/final.json"
    ])
    assert final["policy"] == arm
    assert final["baseline_index"] == pytest.approx(native.index({}))
    assert len(final["questions"]) == 3
    assert all(q["phase"] == "intervention" for q in final["questions"])
    trace = replay(config, native, final)
    assert len(trace) == 4
    assert trace[0] == pytest.approx(final["baseline_index"])
    assert trace[-1] == pytest.approx(final["final_index"])


def test_zero_baseline_valid_only_for_native_fixed_left_right(instrument):
    baseline_defs = instrument.bank("baseline")[:4]
    base = dict(
        study_id="zero-reject",
        question_mode="llm_required",
        response_mode="free_text_multi",
        candidate_mode="native_webapp",
        initial_steps=0,
        intervention_steps=3,
        items=baseline_defs,
    )
    for invalid in ({"fixed_arm": None}, {"fixed_arm": "neutral"},
                    {"fixed_arm": "right", "candidate_mode": "instrument"}):
        with pytest.raises(ValueError, match="zero baseline"):
            StudyConfig(**{**base, **invalid})
    assert StudyConfig(**{**base, "fixed_arm": "left"}).bank("baseline") == []


def test_zero_baseline_attention_positions_can_be_in_adaptive_phase(instrument):
    base = instrument.bank("baseline")[:4]
    config = StudyConfig(
        study_id="zero-attention",
        question_mode="llm_required",
        response_mode="free_text_multi",
        candidate_mode="native_webapp",
        fixed_arm="left",
        initial_steps=0,
        intervention_steps=3,
        items=base,
        attention_checks=(AttentionCheck(
            check_id="attention_reading",
            instruction="Include the word cobalt in your answer to demonstrate attention.",
            expected_token="cobalt",
            render="verbatim",
            after_substantive=2,
        ),),
    )
    assert config.attention_position(config.attention_checks[0]) == 2


@pytest.mark.parametrize("arm", ["left", "right"])
def test_committed_no_calibration_instruments(arm):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "config"
    expected_poles = {"gunlaw", "grass", "abany", "natfare", "natenvir", "natarms"}
    for suffix, reviewed, mandatory in ((".staging", True, False), ("", False, True)):
        conf = StudyConfig.load(root / f"study.prolific.nocal.{arm}{suffix}.yaml")
        assert conf.fixed_arm == arm
        assert conf.initial_steps == 0 and conf.bank("baseline") == []
        assert conf.intervention_steps == 20
        assert conf.candidate_mode == "native_webapp"
        assert conf.push_response_mode == "draw"
        assert conf.reviewed is reviewed
        assert conf.prolific is not None and conf.prolific.required is mandatory
        assert set(conf.excluded_ids) == expected_poles
        assert [conf.attention_position(c) for c in conf.attention_checks] == [3, 7, 11, 15, 19]
        assert len(conf.attention_checks) == 5
        assert len(conf.bank("baseline")) + conf.intervention_steps + len(conf.attention_checks) == 25
        assert conf.study_id != "prolific-v3-human-opinions-2026-10"
        if not reviewed:
            assert conf.prolific.completion_code.startswith("CHANGEME")
            assert len(conf.exclude_prior_study_ids) == 4
