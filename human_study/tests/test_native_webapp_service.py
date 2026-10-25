"""End-to-end V3 native-webapp integration with synthetic LSM and participant.

The native optimizer algorithm comes from the same shared functions; only
model numerics, OpenAI replies and persistence are synthetic in this test.
"""
import json
import re
from types import SimpleNamespace

import pytest

from human_study.adapter import NativeAdapter
from human_study.multi_observations import replay
from human_study.service import StudyService
from human_study.storage import MemoryArchive, MemoryRepository
from human_study.study_config import StudyConfig
from optimizer.one_step_geometry import one_step_geometry


class NativeFixtureAdapter:
    webapp_candidates = NativeAdapter.webapp_candidates
    dynamic_item = NativeAdapter.dynamic_item
    webapp_mapping_items = NativeAdapter.webapp_mapping_items

    def __init__(self, numerical):
        self.numerical = numerical
        self.provenance = numerical.provenance
        names = [f"item_{i:02}" for i in range(50)]
        ctx = SimpleNamespace(
            feat=set(names), idx_map={v: i for i, v in enumerate(names)},
            var_map={v: f"Question about topic {v}?" for v in names},
            possible={v: ["yes", "no"] for v in names},
        )
        self.world = SimpleNamespace(
            ctx=ctx, g=SimpleNamespace(left_map={}, right_map={}),
            text=ctx.var_map,
        )

    def validate_config(self, config):
        for item in config.items:
            assert all(c.native_value in self.support(item.item_id) for c in item.choices)

    def support(self, v):
        return self.numerical.support(v)

    def index(self, state):
        return self.numerical.index(state)

    def distributions(self, state, variables):
        return self.numerical.distributions(state, variables)

    def webapp_scores(self, state, candidates):
        return one_step_geometry(
            state, candidates,
            lambda states: [self.index(s) for s in states],
            self.distributions, text=self.world.text,
        )


class RecordedAnswerLLM:
    def __init__(self):
        self.mapping_inputs = []
        self.generated = []

    def generate(self, item):
        self.generated.append(item.item_id)
        return {
            "displayed_wording": f"About {item.item_id}, what do you think?",
            "question_provenance": {
                "fallback": False, "provider": "synthetic",
                "validation_method": "native_webapp_realistic",
            },
        }

    def map_human_response(self, question, free_text):
        self.mapping_inputs.append((question, free_text))
        target = re.search(r"About (item_\d{2})", question).group(1)
        # A first baseline answer explicitly gives a second opinion.
        ids = [target, "item_24"] if target == "item_00" else [target]
        return {
            "variables": ids, "path": "webapp_direct_mapping",
            "semantic_fallback": "update_state", "response_mode": "draw",
            "source": "dtag_session.DTAGSession.map_question",
        }

    def interpret_multi(self, question, written, allowed_items):
        return {
            "status": "mapped",
            "proposed": [
                {"variable": item.item_id, "native_value": "yes",
                 "confidence": .99, "evidence": "yes"}
                for item in allowed_items
            ],
            "provider": "fixture", "mapping_method": "explicit_evidence_only_v3",
            "rationale": "the participant explicitly expressed an affirmative view",
        }


def test_service_selects_native_dynamic_variables_and_maps_multiple_answers(instrument, adapter):
    config = StudyConfig(
        study_id="native-webapp-service-fixture",
        question_mode="llm_required", response_mode="free_text_multi",
        candidate_mode="native_webapp", push_response_mode="draw",
        initial_steps=4, intervention_steps=3,
        items=instrument.bank("baseline")[:4],
    )
    assert not config.bank("intervention")
    llm = RecordedAnswerLLM()
    repo, archive = MemoryRepository(), MemoryArchive()
    native = NativeFixtureAdapter(adapter)
    svc = StudyService(config, native, llm, repo, archive)
    initial = svc.start()
    view = svc.consent(initial["session_id"], True, initial["session_version"])
    session_id = view["session_id"]
    targets = []
    for step in range(7):
        target = repo.read(session_id).records[
            f"questions/{view['question']['question_id']}"
        ]["target_variable"]
        targets.append(target)
        request = {
            "question_id": view["question"]["question_id"],
            "answer_value": None, "text_answer": "yes, with additional reasons",
            "missing_reason": None, "idempotency_key": f"native-{step}",
            "expected_session_version": view["session_version"],
        }
        view = svc.answer(session_id, request)["current"]
        if step == 3:
            st = repo.read(session_id).session["state"]
            assert len(st["initial_observed_state"]) == 5
            assert st["initial_observed_state"]["item_24"] == "yes"
    assert view["phase"] == "ready_to_complete"
    assert len(targets) == 7
    assert len(set(targets)) == 7
    assert all(t not in {f"item_{i:02}" for i in range(4)} | {"item_24"}
               for t in targets[4:])
    assert len(llm.generated) == 7
    assert len(llm.mapping_inputs) == 7
    svc.complete(session_id)
    name = f"studies/{config.study_id}/sessions/{session_id}/final.json"
    final = json.loads(archive.objects[name])
    assert len(final["questions"]) == 7
    assert all(q["response_interpretation"]["variable_mapping"]["response_mode"] == "draw"
               for q in final["questions"])
    assert len(final["questions"][0]["accepted_assignments"]) == 2
    trace = replay(config, native, final)
    assert len(trace) == 4
    assert trace[-1] == pytest.approx(final["final_index"])


def test_repeated_native_assignment_updates_state_like_DTAGSession(instrument, adapter):
    from human_study.multi_observations import resolve, apply
    from human_study.state import HumanDTAGState
    config = StudyConfig(
        study_id="native-webapp-revision-fixture",
        question_mode="llm_required", response_mode="free_text_multi",
        candidate_mode="native_webapp", push_response_mode="draw",
        initial_steps=4, intervention_steps=3,
        items=instrument.bank("baseline")[:4],
    )
    native = NativeFixtureAdapter(adapter)
    original = {"item_00": "yes"}
    old_index = native.index(original)
    state = HumanDTAGState(
        "s", config.model_key, config.config_hash, native.provenance,
        original, original, (), ("item_00",), (), (), old_index, old_index,
    )
    proposal = {
        "status": "mapped", "proposed": [
            {"variable": "item_00", "native_value": "no",
             "confidence": .99, "evidence": "no"},
        ],
        "provider": "fixture", "rationale": "explicit changed opinion",
    }
    mapped_items = native.webapp_mapping_items(["item_00"], config)
    resolved = resolve(
        proposal, "I now say no", mapped_items, original, native, .8,
        allow_revision=True,
    )
    assert len(resolved["conflicts"]) == 1
    assert resolved["conflicts"][0]["prior_native_value"] == "yes"
    assert resolved["accepted"][0]["revises_prior"] is True
    q = {
        "question_id": "revised", "target_variable": "item_05",
        "selection": {
            "candidate_mode": "native_webapp", "expected_delta": 0.01,
        },
        "conditional_distribution": {"yes": .6, "no": .4},
    }
    updated, result = apply(state, q, resolved["accepted"], native)
    assert updated.observed_state["item_00"] == "no"
    assert result["index_after"] == pytest.approx(native.index({"item_00": "no"}))
    assert result["observed_conditional_index_delta"] == pytest.approx(
        result["index_after"] - old_index)
    assert len(updated.observations) == 1
