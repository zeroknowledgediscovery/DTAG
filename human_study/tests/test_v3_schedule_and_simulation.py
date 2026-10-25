"""Automated full-session V3 tests: no human responses or OpenAI API required.

Exercise the real state machine, LSM geometry interface, idempotent commits and
archive, with a synthetic native adapter and deterministic scripted respondent.
The full 6+20+5 run is a sizing/scheduling test, NOT native-GSS validation.
"""
from __future__ import annotations

import json

import pytest

from human_study.multi_observations import replay
from human_study.service import StudyService
from human_study.storage import MemoryArchive, MemoryRepository
from human_study.study_config import StudyConfig
from test_v3_multi_observations import MultiFixtureLLM, make_v3, request


def configured(config, locations, *, study_id):
    base = config.model_dump(mode="json")
    base["study_id"] = study_id
    base["attention_checks"] = [
        {
            "check_id": f"attention_{i:02}",
            "instruction": f"For reading check {i}, please include the exact word cobalt in your reply.",
            "expected_token": "cobalt",
            "after_substantive": pos,
        }
        for i, pos in enumerate(locations, 1)
    ]
    return StudyConfig.model_validate(base)


def run_session(config, adapter, llm):
    """Scripted respondent; never communicates with a live API."""
    repo, archive = MemoryRepository(), MemoryArchive()
    svc = StudyService(config, adapter, llm, repo, archive)
    first = svc.start()
    view = svc.consent(first["session_id"], True, first["session_version"])
    sid = first["session_id"]
    seen = []
    before_attention = {}
    total = (len(config.bank("baseline")) + config.intervention_steps +
             len(config.attention_checks))
    for ordinal in range(total):
        assert view["question"] is not None, (ordinal, view)
        question_id = view["question"]["question_id"]
        q = repo.read(sid).records[f"questions/{question_id}"]
        seen.append((view["phase"], q["target_variable"]))
        if view["phase"] == "attention":
            before_attention[question_id] = repo.read(sid).session["state"]
            answer = "I am paying attention: cobalt."
        else:
            answer = "yes, and also no"
        payload = request(view, answer)
        accepted = svc.answer(sid, payload)
        assert accepted["accepted"]["accepted"] is True
        assert accepted["current"]["progress"]["completed"] == ordinal + 1
        view = accepted["current"]
        if q["phase"] == "attention":
            assert repo.read(sid).session["state"] == before_attention[question_id]
        # Replay the exact POST; it cannot append a second observation.
        if ordinal in {0, total // 2, total - 1}:
            again = svc.answer(sid, payload)
            assert again["accepted"]["question_id"] == payload["question_id"]
            assert again["current"]["progress"]["completed"] == ordinal + 1
    assert view["phase"] == "ready_to_complete"
    completed = svc.complete(sid)
    assert completed["phase"] == "complete"
    name = f"studies/{config.study_id}/sessions/{sid}/final.json"
    final = json.loads(archive.objects[name])
    assert len(final["questions"]) == total
    assert len(set(q["question_id"] for q in final["questions"])) == total
    assert len([q for q in final["questions"] if q["phase"] == "attention"]) == len(config.attention_checks)
    assert [q["attention_passed"] for q in final["questions"] if q["phase"] == "attention"] == [True] * len(config.attention_checks)
    trajectory = replay(config, adapter, final)
    assert len(trajectory) == config.intervention_steps + 1
    assert trajectory[-1] == pytest.approx(final["final_index"])
    assert all(q["question_provenance"]["fallback"] is False for q in final["questions"])
    return seen, final


def test_checks_before_between_and_after_short_4_plus_3(instrument, adapter):
    config, _, _ = make_v3(instrument, adapter)
    positions = [0, 2, 4, 5, 7]
    config = configured(config, positions, study_id="v3-interleaved-seven")
    seen, final = run_session(config, adapter, MultiFixtureLLM())
    assert len(seen) == 12
    substantive = 0
    encountered = []
    for phase, _ in seen:
        if phase == "attention":
            encountered.append(substantive)
        else:
            assert phase in ("baseline", "intervention")
            substantive += 1
    assert encountered == positions
    assert substantive == 7


def test_adjacent_checks_same_boundary_resume_once(instrument, adapter):
    config, _, _ = make_v3(instrument, adapter)
    positions = [2, 2, 7]
    config = configured(config, positions, study_id="v3-adjacent-checks")
    seen, _ = run_session(config, adapter, MultiFixtureLLM())
    assert [phase for phase, _ in seen].count("attention") == 3
    assert [phase for phase, _ in seen].count("baseline") == 4
    assert [phase for phase, _ in seen].count("intervention") == 3


def test_long_full_length_6_baseline_20_adaptive_5_attention(instrument, adapter):
    base = StudyConfig(
        study_id="v3-long-synthetic",
        question_mode="llm_required",
        response_mode="free_text_multi",
        initial_steps=6,
        intervention_steps=20,
        items=(*instrument.bank("baseline")[:6],
               *instrument.bank("intervention")),
    )
    positions = [3, 8, 13, 18, 24]
    config = configured(base, positions, study_id="v3-long-synthetic-checks")
    seen, final = run_session(config, adapter, MultiFixtureLLM())
    assert len(seen) == 31
    assert sum(p == "baseline" for p, _ in seen) == 6
    assert sum(p == "intervention" for p, _ in seen) == 20
    assert sum(p == "attention" for p, _ in seen) == 5
    assert len(final["questions"]) == 31
    first_assigned = final["questions"][0]["accepted_assignments"]
    assert len(first_assigned) >= 2  # multi-item observation is live


def test_schedule_rejects_unsorted_and_out_of_bounds(instrument, adapter):
    config, _, _ = make_v3(instrument, adapter)
    original = config.model_dump(mode="json")
    original["attention_checks"] = [
        {"check_id": "attention_a", "instruction": "Include the exact word cobalt in this answer.",
         "expected_token": "cobalt", "after_substantive": 5},
        {"check_id": "attention_b", "instruction": "Include the exact word cobalt in this answer.",
         "expected_token": "cobalt", "after_substantive": 2},
    ]
    with pytest.raises(ValueError, match="sorted"):
        StudyConfig.model_validate(original)
    original["attention_checks"] = [original["attention_checks"][0] | {"after_substantive": 8}]
    with pytest.raises(ValueError, match="outside"):
        StudyConfig.model_validate(original)
