"""V2: no click categories, no question fallback, and exactly 4+3 archived answers."""
import json

import pytest
from fastapi.testclient import TestClient

from human_study.app import create_app
from human_study.questions import AnswerNeedsClarification
from human_study.service import StudyService
from human_study.storage import MemoryArchive, MemoryRepository
from human_study.study_config import StudyConfig


class V2FixtureLLM:
    def __init__(self):
        self.generated = []
        self.interpreted = []
        self.ambiguous = False

    def generate(self, item):
        self.generated.append(item.item_id)
        return {
            "displayed_wording": f"For topic {item.item_id}, what is your view?",
            "question_provenance": {
                "provider": "fixture-llm", "fallback": False, "mapper_hit": True,
                "input_item_id": item.item_id,
            },
        }

    def interpret(self, item, question, response):
        self.interpreted.append((item.item_id, question, response))
        if self.ambiguous:
            raise AnswerNeedsClarification(
                "We could not confidently interpret that response. Please clarify your view."
            )
        return "yes", None, {
            "provider": "fixture-llm", "status": "mapped", "confidence": 0.99,
            "reason": "respondent explicitly supports the first option",
        }


def make_v2(instrument, adapter):
    items = (
        *instrument.bank("baseline")[:4],
        *instrument.bank("intervention")[:8],
    )
    config = StudyConfig(
        study_id="v2-fixture",
        response_mode="free_text_llm",
        question_mode="llm_required",
        intervention_steps=3,
        items=items,
    )
    llm = V2FixtureLLM()
    repo = MemoryRepository()
    archive = MemoryArchive()
    return config, llm, StudyService(config, adapter, llm, repo, archive)


def text_request(view, raw, key=None):
    return {
        "question_id": view["question"]["question_id"],
        "answer_value": None,
        "text_answer": raw,
        "missing_reason": None,
        "idempotency_key": key or view["question"]["question_id"],
        "expected_session_version": view["session_version"],
    }


def test_v2_exact_4_initial_3_adaptive_without_outcome(instrument, adapter):
    config, llm, svc = make_v2(instrument, adapter)
    initial = svc.start()
    view = svc.consent(initial["session_id"], True, initial["session_version"])
    sid = view["session_id"]
    assert view["progress"] == {"completed": 0, "total": 7}
    asked = []
    for step in range(7):
        assert view["phase"] == ("baseline" if step < 4 else "intervention")
        assert view["question"]["response_mode"] == "free_text_llm"
        raw = f"I favor the first option, because of my values, step {step}."
        req = text_request(view, raw)
        accepted = svc.answer(sid, req)
        assert accepted["accepted"]["accepted"]
        asked.append(req["question_id"])
        view = accepted["current"]
        assert view["progress"]["completed"] == step + 1
    assert view["phase"] == "ready_to_complete"
    assert len(set(asked)) == 7
    assert len(llm.generated) == 7
    assert len(llm.interpreted) == 7
    completed = svc.complete(sid)
    assert completed["phase"] == "complete"
    assert completed["receipt"]
    name = f"studies/{config.study_id}/sessions/{sid}/final.json"
    final = json.loads(svc.archive.objects[name])
    assert len(final["questions"]) == 7
    assert [q["phase"] for q in final["questions"]] == ["baseline"] * 4 + ["intervention"] * 3
    for step, q in enumerate(final["questions"]):
        assert q["response_value"] == "yes"
        assert q["raw_text_response"] == f"I favor the first option, because of my values, step {step}."
        assert q["response_interpretation"]["provider"] == "fixture-llm"
        assert not q["question_provenance"]["fallback"]
        assert q["displayed_wording"] != q["original_wording"]


def test_v2_rejects_clicks_and_ambiguous_free_text_without_advancing(instrument, adapter):
    config, llm, svc = make_v2(instrument, adapter)
    app = create_app(svc, cookie_secret="test-only-stable-secret-0123456789abcdef")
    with TestClient(app) as client:
        h = {"Origin": "http://testserver"}
        start = client.post("/api/human/start", json={}, headers=h).json()
        view = client.post("/api/human/consent", headers=h, json={
            "accepted": True, "expected_session_version": start["session_version"]
        }).json()
        sid = view["session_id"]
        req = text_request(view, "I think generally yes.")
        click = client.post("/api/human/answer", headers=h,
                            json={**req, "answer_value": "yes", "text_answer": None})
        assert click.status_code == 422
        llm.ambiguous = True
        not_understood = client.post("/api/human/answer", headers=h, json=req)
        assert not_understood.status_code == 422
        assert "clarify" in not_understood.json()["detail"].lower()
        snap = svc.repo.read(sid)
        assert snap.session["next_step"] == 0
        assert snap.records[f"questions/{view['question']['question_id']}"]["status"] == "presented"
        llm.ambiguous = False
        valid = client.post("/api/human/answer", headers=h, json=req)
        assert valid.status_code == 200
        assert valid.json()["current"]["progress"]["completed"] == 1


def test_v2_configuration_rejects_unbacked_short_bank(instrument):
    with pytest.raises(ValueError):
        StudyConfig(
            study_id="invalid-v2", question_mode="llm_required",
            response_mode="free_text_llm", intervention_steps=10,
            items=(*instrument.bank("baseline")[:4], *instrument.bank("intervention")[:3]),
        )
