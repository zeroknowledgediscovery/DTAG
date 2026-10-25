"""V3 human answers can contain multiple independently validated GSS observations."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from human_study.app import create_app
from human_study.multi_observations import (
    initial_state, apply, permitted_items, resolve,
)
from human_study.questions import AnswerNeedsClarification, QuestionLLM
from human_study.service import StudyService
from human_study.storage import MemoryArchive, MemoryRepository
from human_study.study_config import StudyConfig


class MultiFixtureLLM:
    def __init__(self):
        self.generation_calls = []
        self.mapping_calls = []
        self.ambiguous = False

    def generate(self, item):
        self.generation_calls.append(item.item_id)
        return {"displayed_wording": f"For topic {item.item_id}, what is your view?",
                "question_provenance": {"provider": "fixture-llm", "fallback": False,
                                        "mapper_hit": True, "input_item_id": item.item_id}}

    def generate_attention(self, check):
        self.generation_calls.append(check.check_id)
        return {
            "displayed_wording": (
                f"For this attention check, please include the word "
                f"{check.expected_token} in your answer?"
            ),
            "question_provenance": {
                "provider": "fixture-llm", "fallback": False,
                "validation_method": "exact_attention_token_preserved_v3",
            },
        }

    def interpret_multi(self, question, words, allowed_items):
        self.mapping_calls.append((question, words))
        if self.ambiguous:
            return {"status": "ambiguous", "proposed": [], "rationale": "unclear",
                    "provider": "fixture", "mapping_method": "explicit_evidence_only_v3"}
        target = re.search(r"topic (item_\d+)", question).group(1)
        proposed = [{"variable": target, "native_value": "yes", "confidence": .97,
                     "evidence": "yes"}]
        if target == "item_00":
            proposed.append({"variable": "item_13", "native_value": "yes",
                             "confidence": .96, "evidence": "yes"})
        if target == "item_01":
            proposed.append({"variable": "item_13", "native_value": "no",
                             "confidence": .94, "evidence": "no"})
        return {"status": "mapped", "proposed": proposed, "rationale": "explicit",
                "provider": "fixture", "mapping_method": "explicit_evidence_only_v3"}


def make_v3(instrument, adapter):
    items = (*instrument.bank("baseline")[:4], *instrument.bank("intervention")[:8])
    config = StudyConfig(
        study_id="v3-fixture", question_mode="llm_required",
        response_mode="free_text_multi", initial_steps=4,
        intervention_steps=3, max_response_assignments=5, items=items,
    )
    llm = MultiFixtureLLM()
    service = StudyService(config, adapter, llm, MemoryRepository(), MemoryArchive())
    return config, llm, service


def request(view, raw, idempotency_key=None):
    return {
        "question_id": view["question"]["question_id"],
        "answer_value": None,
        "text_answer": raw,
        "missing_reason": None,
        "idempotency_key": idempotency_key or view["question"]["question_id"],
        "expected_session_version": view["session_version"],
    }


def test_v3_four_initial_three_adaptive_with_five_baseline_coordinates(instrument, adapter):
    config, llm, service = make_v3(instrument, adapter)
    start = service.start()
    view = service.consent(start["session_id"], True, start["session_version"])
    sid = view["session_id"]
    for i in range(4):
        raw = "yes, and also no" if i == 1 else "yes, with additional reasons"
        view = service.answer(sid, request(view, raw))["current"]
    assert view["phase"] == "intervention"
    snap = service.repo.read(sid)
    baseline = dict(snap.session["state"]["initial_observed_state"])
    assert len(baseline) == 5   # four initial QUESTIONS, five mapped VARIABLES
    assert baseline == {"item_00": "yes", "item_13": "yes", "item_01": "yes",
                        "item_02": "yes", "item_03": "yes"}
    assert snap.session["state"]["baseline_index"] == adapter.index(baseline)
    assert view["question"]["response_mode"] == "free_text_multi"
    asked_adaptive = []
    for i in range(3):
        var = next(v["target_variable"] for k, v in service.repo.read(sid).records.items()
                   if k.startswith("questions/") and v["question_id"] == view["question"]["question_id"])
        assert var != "item_13"  # already learned from initial free text
        asked_adaptive.append(var)
        view = service.answer(sid, request(view, "yes, a clear opinion"))["current"]
    assert view["phase"] == "ready_to_complete"
    assert len(set(asked_adaptive)) == 3
    assert len(llm.generation_calls) == 7
    assert len(llm.mapping_calls) == 7
    final_view = service.complete(sid)
    final_name = f"studies/{config.study_id}/sessions/{sid}/final.json"
    final = json.loads(service.archive.objects[final_name])
    assert final_view["phase"] == "complete" and len(final["questions"]) == 7
    qs = sorted(final["questions"], key=lambda q: q["ordinal"])
    assert len(qs[0]["accepted_assignments"]) == 2
    assert any(c["variable"] == "item_13" and c["prior_native_value"] == "yes"
               for c in qs[1]["response_interpretation"]["conflicts"])
    assert qs[1]["response_interpretation"]["accepted"] == qs[1]["accepted_assignments"]
    assert all(q["raw_text_response"] and q["question_provenance"]["fallback"] is False
               for q in qs)
    assert all(q["response_interpretation"]["mapping_method"] == "explicit_evidence_only_v3"
               for q in qs)
    observed = baseline.copy()
    before = final["baseline_index"]
    for q in qs[4:]:
        result = q["index_result"]
        assert result["index_before"] == pytest.approx(before)
        for a in q["accepted_assignments"]:
            observed[a["variable"]] = a["native_value"]
        before = adapter.index(observed)
        assert result["index_after"] == pytest.approx(before)
        assert result["predicted_delta_scope"] == "selected_target_only"
        assert result["observed_delta_scope"] == "all_new_explicit_assignments"
    assert before == pytest.approx(final["final_index"])
    from human_study.multi_observations import replay
    trace = replay(config, adapter, final)
    assert len(trace) == 4
    assert trace[-1] == pytest.approx(final["final_index"])


def test_v3_rejects_unjustified_assignments_and_preserves_prior_conflicts(instrument, adapter):
    config, llm, service = make_v3(instrument, adapter)
    allowed = permitted_items(config, adapter)
    prior = {"item_13": "yes"}
    response = {
        "status": "mapped", "provider": "fixture", "rationale": "test", "proposed": [
            {"variable": "item_14", "native_value": "no", "confidence": .99, "evidence": "no"},
            {"variable": "item_13", "native_value": "no", "confidence": .99, "evidence": "no"},
            {"variable": "item_15", "native_value": "yes", "confidence": .99, "evidence": "not a real quote"},
            {"variable": "item_16", "native_value": "yes", "confidence": .10, "evidence": "yes"},
            {"variable": "item_17", "native_value": "unrecognized", "confidence": .99, "evidence": "yes"},
            {"variable": "item_99", "native_value": "yes", "confidence": .99, "evidence": "yes"},
        ],
    }
    resolved = resolve(response, "no, although yes", allowed, prior, adapter, .8)
    assert [a["variable"] for a in resolved["accepted"]] == ["item_14"]
    assert resolved["conflicts"][0]["variable"] == "item_13"
    assert prior == {"item_13": "yes"}
    assert {a["reason"] for a in resolved["rejected"]} == {
        "evidence_not_quoted_from_response", "below_confidence_threshold",
        "category_not_in_approved_item", "unreviewed_or_reserved_variable",
    }


def test_v3_empty_ambiguous_response_does_not_advance(instrument, adapter):
    _, llm, service = make_v3(instrument, adapter)
    app = create_app(service, cookie_secret="v3-test-secret-0123456789abcdef")
    with TestClient(app) as client:
        headers = {"Origin": "http://testserver"}
        start = client.post("/api/human/start", headers=headers, json={}).json()
        view = client.post("/api/human/consent", headers=headers, json={
            "accepted": True, "expected_session_version": start["session_version"]
        }).json()
        req = request(view, "unclear narrative")
        llm.ambiguous = True
        res = client.post("/api/human/answer", headers=headers, json=req)
        assert res.status_code == 422
        assert "clarify" in res.json()["detail"].lower()
        assert service.repo.read(view["session_id"]).session["next_step"] == 0
        llm.ambiguous = False
        res = client.post("/api/human/answer", headers=headers, json={**req, "text_answer": "yes"})
        assert res.status_code == 200
        assert res.json()["current"]["progress"]["completed"] == 1


def test_v3_llm_multi_response_schema(instrument, adapter):
    from types import SimpleNamespace
    config, _, _ = make_v3(instrument, adapter)
    llm = QuestionLLM(adapter, config)
    class Responses:
        def create(self, **kwargs):
            schema = kwargs["text"]["format"]["schema"]
            assert schema["properties"]["assignments"]["maxItems"] == 5
            assert "item_13" in kwargs["input"]
            return SimpleNamespace(output_text=json.dumps({
                "status": "mapped", "assignments": [
                    {"variable": "item_00", "native_value": "yes",
                     "confidence": .99, "evidence": "yes"},
                    {"variable": "item_13", "native_value": "no",
                     "confidence": .97, "evidence": "no"},
                ],
                "rationale": "two explicitly stated beliefs",
            }))
    llm.client = SimpleNamespace(responses=Responses())
    result = llm.interpret_multi("Do you think it is fair?", "yes and no", 
                                  list(permitted_items(config, adapter).values()))
    assert len(result["proposed"]) == 2
    assert result["mapping_method"] == "explicit_evidence_only_v3"


@pytest.mark.parametrize("written,expected_passed", [
    ("I followed the instruction: cobalt.", True),
    ("I did not include the requested word.", False),
])
def test_attention_check_is_llm_worded_and_excluded_from_ideology(
    instrument, adapter, written, expected_passed
):
    from human_study.study_config import AttentionCheck

    config, llm, _ = make_v3(instrument, adapter)
    check = AttentionCheck(
        check_id="attention_reading",
        instruction="For this reading check, include the exact word cobalt in your reply.",
        expected_token="cobalt",
    )
    config = config.model_copy(update={"study_id": "v3-fixture-with-attention",
                                      "attention_checks": (check,)})
    service = StudyService(config, adapter, llm, MemoryRepository(), MemoryArchive())
    initial = service.start()
    view = service.consent(initial["session_id"], True, initial["session_version"])
    sid = view["session_id"]
    assert view["progress"]["total"] == 8
    for _ in range(7):
        view = service.answer(sid, request(view, "yes, and also no"))["current"]
    assert view["phase"] == "attention"
    assert view["progress"]["completed"] == 7
    assert "cobalt" in view["question"]["text"]
    before_state = service.repo.read(sid).session["state"].copy()
    accepted = service.answer(sid, request(view, written))
    assert accepted["current"]["phase"] == "ready_to_complete"
    assert accepted["current"]["progress"]["completed"] == 8
    after_state = service.repo.read(sid).session["state"]
    assert after_state == before_state  # attention must not condition native model

    final_view = service.complete(sid)
    name = f"studies/{config.study_id}/sessions/{sid}/final.json"
    final = json.loads(service.archive.objects[name])
    attention = final["questions"][-1]
    assert final_view["phase"] == "complete"
    assert attention["phase"] == "attention"
    assert attention["attention_passed"] is expected_passed
    assert attention["accepted_assignments"] == []
    assert "index_result" not in attention
    assert attention["question_provenance"]["fallback"] is False
    assert len(llm.generation_calls) == 8
    from human_study.multi_observations import replay
    assert len(replay(config, adapter, final)) == 4


def test_v3_llm_attention_generation_preserves_required_token(instrument, adapter):
    from types import SimpleNamespace
    from human_study.questions import QuestionGenerationError
    from human_study.study_config import AttentionCheck

    config, _, _ = make_v3(instrument, adapter)
    check = AttentionCheck(
        check_id="attention_reading",
        instruction="For the reading test, include the exact word cobalt in your reply.",
        expected_token="cobalt",
    )
    llm = QuestionLLM(adapter, config)
    class Responses:
        text = "To show you read this, could you include the word cobalt in your answer?"
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps({"question": self.text}))
    client = Responses()
    llm.client = SimpleNamespace(responses=client)
    generated = llm.generate_attention(check)
    assert "cobalt" in generated["displayed_wording"]
    assert generated["question_provenance"]["fallback"] is False
    # The generator retries invalid wording three times and then raises a
    # bounded, actionable error; the old "integrity" message was removed.
    client.text = "Have you read the question?"
    with pytest.raises(QuestionGenerationError, match="valid instructed-response") as exc:
        llm.generate_attention(check)
    assert exc.value.attempts == [
        {"attempt": n, "error": "invalid_generated_instruction"} for n in (1, 2, 3)
    ]

    # Returning the source instruction verbatim is also rejected: questions
    # must be LLM-written, never fall back to unmodified investigator wording.
    client.text = check.instruction
    with pytest.raises(QuestionGenerationError, match="valid instructed-response") as exc:
        llm.generate_attention(check)
    assert len(exc.value.attempts) == 3
    assert all(a["error"] == "invalid_generated_instruction"
               for a in exc.value.attempts)


def test_v3_committed_last_adaptive_answer_is_acknowledged_during_attention_generation_failure(
    instrument, adapter
):
    """Simulate the 6/8 -> childcare -> 7/8 pending attention failure seen live.

    The 7th written response MUST be committed once, ACKed by HTTP, and never
    mistaken for an unsaved answer when the subsequent LLM generation fails.
    """
    import time
    from human_study.questions import QuestionGenerationError
    from human_study.study_config import AttentionCheck

    config, _, _ = make_v3(instrument, adapter)
    check = AttentionCheck(
        check_id="attention_reading",
        instruction="For this reading check, include the exact word cobalt in your reply.",
        expected_token="cobalt",
    )
    config = config.model_copy(update={
        "study_id": "v3-pending-next-question",
        "attention_checks": (check,),
    })

    class FailFirstAttention(MultiFixtureLLM):
        def __init__(self):
            super().__init__()
            self.failures = 0

        def generate_attention(self, check):
            if self.failures == 0:
                self.failures += 1
                raise QuestionGenerationError("simulated temporary invalid attention wording")
            return super().generate_attention(check)

    llm = FailFirstAttention()
    repo = MemoryRepository()
    service = StudyService(config, adapter, llm, repo, MemoryArchive())
    initial = service.start()
    view = service.consent(initial["session_id"], True, initial["session_version"])
    sid = view["session_id"]
    for _ in range(6):
        view = service.answer(sid, request(view, "yes, and also no"))["current"]
    assert view["progress"]["completed"] == 6
    assert view["phase"] == "intervention"
    childcare_request = request(view, "yes, with reasons for this final adaptive response")
    saved = service.answer(sid, childcare_request)
    assert saved["accepted"]["accepted"] is True
    assert saved["preparing_next"] is True
    assert saved["current"]["progress"]["completed"] == 7
    assert saved["current"]["phase"] == "attention"
    assert saved["current"]["question"] is None
    assert llm.failures == 1

    # Repeating the same idempotent POST must NOT write a second observation
    # or return 503 merely because the next question still needs generation.
    repeated = service.answer(sid, childcare_request)
    assert repeated["accepted"]["question_id"] == saved["accepted"]["question_id"]
    assert repeated["current"]["progress"]["completed"] == 7
    snap = repo.read(sid)
    assert len([q for key, q in snap.records.items()
                if key.startswith("questions/") and q.get("status") == "answered"]) == 7

    # Simulate elapsed retry lease. The same study session must recover.
    generating = [(key, q) for key, q in snap.records.items()
                  if key.startswith("questions/") and q.get("status") == "generating"]
    assert len(generating) == 1
    key, q = generating[0]
    q["generation_lease_until"] = time.time() - 1
    assert repo.cas(sid, snap.session["revision"], snap.session, {key: q})
    view = service.current(sid)
    assert view["phase"] == "attention"
    assert view["question"]["text"].endswith("?")
    assert "cobalt" in view["question"]["text"]
    completed_attention = service.answer(sid, request(view, "cobalt"))
    assert completed_attention["current"]["phase"] == "ready_to_complete"
    final = service.complete(sid)
    assert final["phase"] == "complete"


def test_v3_attention_accepts_generated_imperative_and_retries_invalid_first_attempt(
    instrument, adapter
):
    """The model must generate the instruction; punctuation alone is not failure."""
    from types import SimpleNamespace
    from human_study.study_config import AttentionCheck
    check = AttentionCheck(
        check_id="attention_retry_test",
        instruction="Please write the word cobalt as part of your response to this attention check.",
        expected_token="cobalt",
    )
    config, _, _ = make_v3(instrument, adapter)
    llm = QuestionLLM(adapter, config)

    class Responses:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            wording = (
                "What color word do you see above?"
                if self.calls == 1 else
                "Please include the word cobalt in your written answer."
            )
            return SimpleNamespace(output_text=json.dumps({"question": wording}))

    responses = Responses()
    llm.client = SimpleNamespace(responses=responses)
    rendered = llm.generate_attention(check)
    assert responses.calls == 2
    assert rendered["displayed_wording"].endswith(".")
    assert rendered["question_provenance"]["generation_attempts"] == 2
    assert rendered["question_provenance"]["fallback"] is False


@pytest.mark.parametrize("phase", ["baseline", "attention"])
def test_v3_archive_outage_cannot_be_reported_as_next_question_pending(
    instrument, adapter, phase
):
    """GCS failures must propagate even after a Firestore answer commit.

    Tests both the normal written-answer path and the standalone V3 attention
    path, including replaying a committed idempotency key during an outage.
    """
    from human_study.service import ExportPending
    from human_study.study_config import AttentionCheck, digest

    config, llm, service = make_v3(instrument, adapter)
    if phase == "attention":
        check = AttentionCheck(
            check_id="attention_persistence",
            instruction="For this attention check, include the word cobalt in your reply.",
            expected_token="cobalt",
        )
        config = config.model_copy(update={
            "study_id": "v3-attention-persistence",
            "attention_checks": (check,),
        })
        service = StudyService(config, adapter, llm, MemoryRepository(), MemoryArchive())

    initial = service.start()
    view = service.consent(initial["session_id"], True, initial["session_version"])
    sid = view["session_id"]
    if phase == "attention":
        for _ in range(7):
            view = service.answer(sid, request(view, "yes, and also no"))["current"]
        assert view["phase"] == "attention"
    else:
        assert view["phase"] == "baseline"

    expected_completed = view["progress"]["completed"] + 1
    req = request(view, "cobalt" if phase == "attention" else "yes, and also no")
    real_put = service.archive.put

    def failed_put(*args):
        raise OSError("injected GCS outage")

    service.archive.put = failed_put
    try:
        with pytest.raises(ExportPending):
            service.answer(sid, req)
        snap = service.repo.read(sid)
        assert snap.session["next_step"] == expected_completed
        assert snap.session["pending_exports"]
        assert snap.session["current_question_id"] is None
        assert snap.records["requests/" + digest(
            req["idempotency_key"]
        )]["result"]["accepted"] is True

        with pytest.raises(ExportPending):
            service.current(sid)
        with pytest.raises(ExportPending):
            service.answer(sid, req)  # idempotent repeat cannot falsely ACK
        after_retry = service.repo.read(sid)
        assert after_retry.session["next_step"] == expected_completed
        assert sum(
            q["status"] == "answered"
            for k, q in after_retry.records.items()
            if k.startswith("questions/")
        ) == expected_completed
    finally:
        service.archive.put = real_put

    recovered = service.answer(sid, req)
    assert recovered["accepted"]["accepted"] is True
    assert recovered["preparing_next"] is False
    assert recovered["current"]["progress"]["completed"] == expected_completed
    assert not service.repo.read(sid).session["pending_exports"]
    if phase == "attention":
        assert recovered["current"]["phase"] == "ready_to_complete"
    else:
        assert recovered["current"]["question"]["question_id"] != req["question_id"]
