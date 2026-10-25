import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from human_study.local_fixture import LocalLLM as FixtureLLM
from human_study.service import StudyService, ExportPending, GenerationPending
from human_study.storage import MemoryArchive, MemoryRepository, Conflict, IntegrityError
from human_study.storage_firestore import encode, decode


def make_service(config, adapter, repo=None, archive=None, hook=None):
    return StudyService(config, adapter, FixtureLLM(), repo or MemoryRepository(), archive or MemoryArchive(), failure_hook=hook)


def request(view, value="yes", key=None):
    return {"question_id": view["question"]["question_id"], "answer_value": value, "missing_reason": None,
            "idempotency_key": key or view["question"]["question_id"], "expected_session_version": view["session_version"]}


def consent(svc):
    view = svc.start()
    return svc.consent(view["session_id"], True, view["session_version"])


def finish(svc, view):
    while view["phase"] not in ("ready_to_complete", "complete"):
        view = svc.answer(view["session_id"], request(view))["current"]
    return svc.complete(view["session_id"])


def test_full_flow_exact_archive_and_outcome_separation(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    sid = view["session_id"]
    baseline_state = None
    intervention_state = None
    while view["phase"] != "ready_to_complete":
        snap = svc.repo.read(sid)
        if view["phase"] == "baseline":
            assert snap.session["policy"] is None
        if view["phase"] == "intervention" and baseline_state is None:
            baseline_state = copy.deepcopy(snap.session["state"])
        if view["phase"] == "outcome":
            if intervention_state is None:
                intervention_state = copy.deepcopy(snap.session["state"])
            assert snap.session["state"] == intervention_state
        assert not any(x in json.dumps(view) for x in ("expected_delta", "index_before", "policy", "provenance"))
        view = svc.answer(sid, request(view))["current"]
    final = svc.complete(sid)
    assert final["phase"] == "complete" and final["receipt"]
    assert svc.complete(sid)["receipt"] == final["receipt"]
    blob = json.loads(svc.archive.objects[f"studies/{instrument.study_id}/sessions/{sid}/final.json"])
    assert len(blob["questions"]) == 13 + 20 + 4
    assert len(blob["source_objects"]) == (13 + 20 + 4) * 2 + 2
    assert blob["policy"] in ("right", "left", "neutral", "random")
    assert blob["baseline_index"] == baseline_state["baseline_index"]
    assert blob["final_index"] == intervention_state["current_index"]
    assert all(q["displayed_wording"] and q["response_value"] == "yes" for q in blob["questions"])
    assert all("predicted_model_delta" in q["index_result"] for q in blob["questions"] if q["phase"] == "intervention")
    assert all(name in svc.archive.objects for name in blob["source_objects"])


@pytest.mark.parametrize("point", ["before_answer_transaction", "after_answer_transaction", "before_gcs_create",
    "after_gcs_create", "before_export_commit", "after_export_commit"])
def test_crash_reconciliation_at_every_boundary(instrument, adapter, point):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    sid, req = view["session_id"], request(view)
    failures = []
    def crash(p):
        if p == point and not failures:
            failures.append(p)
            raise RuntimeError("injected crash")
    svc.hook = crash
    with pytest.raises((RuntimeError, ExportPending)):
        svc.answer(sid, req)
    assert failures == [point]
    # Process restart: all operational state and wording comes from the shared repository.
    restarted = make_service(instrument, adapter, svc.repo, svc.archive)
    if point == "before_answer_transaction":
        assert restarted.current(sid)["question"] == view["question"]
    accepted = restarted.answer(sid, req)
    repeat = restarted.answer(sid, req)
    assert accepted["accepted"] == repeat["accepted"]
    snap = restarted.repo.read(sid)
    assert sum(q.get("status") == "answered" for k, q in snap.records.items() if k.startswith("questions/")) == 1
    assert not snap.session["pending_exports"]
    assert restarted.current(sid)["question"] != view["question"]


def test_archive_outage_blocks_advancement_and_completion(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    real_put = svc.archive.put
    def down(*args):
        raise OSError("GCS unavailable")
    svc.archive.put = down
    with pytest.raises(ExportPending):
        svc.answer(view["session_id"], request(view))
    snap = svc.repo.read(view["session_id"])
    assert snap.session["pending_exports"]
    assert snap.session["next_step"] == 1  # accepted durably, but no next question presented
    assert sum(k.startswith("questions/") for k in snap.records) == 1
    with pytest.raises(ExportPending):
        svc.current(view["session_id"])
    svc.archive.put = real_put
    recovered = svc.answer(view["session_id"], request(view))
    assert recovered["accepted"]["accepted"]
    assert recovered["current"]["question"]["question_id"] != view["question"]["question_id"]


def test_concurrent_double_click_and_conflicts(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    sid, req = view["session_id"], request(view)

    def same_request_with_pending_retry(_):
        # The answer may already be durably committed while another thread
        # prepares the next question. GenerationPending is an intentional,
        # retryable state; resubmit the exact same idempotency key.
        deadline = time.monotonic() + 10
        while True:
            try:
                return svc.answer(sid, req)
            except GenerationPending:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(same_request_with_pending_retry, range(4)))
    assert len({json.dumps(o["accepted"], sort_keys=True) for o in outcomes}) == 1
    snap = svc.repo.read(sid)
    assert snap.session["next_step"] == 1
    with pytest.raises(Conflict):
        svc.answer(sid, {**req, "answer_value": "no"})
    with pytest.raises(Conflict):
        svc.answer(sid, {**req, "idempotency_key": "different-key"})
    with pytest.raises(Conflict):
        svc.answer(sid, {**request(outcomes[0]["current"]), "expected_session_version": 0})


def test_restart_and_current_preserve_exact_generated_wording(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    for _ in range(13):
        view = svc.answer(view["session_id"], request(view))["current"]
    assert view["phase"] == "intervention"
    assert svc.llm.calls == 1
    restarted = make_service(instrument, adapter, svc.repo, svc.archive)
    with ThreadPoolExecutor(max_workers=4) as pool:
        views = list(pool.map(lambda _: restarted.current(view["session_id"]), range(8)))
    assert all(v["question"] == view["question"] for v in views)
    assert restarted.llm.calls == 0


def test_missingness_stays_outside_native_state(instrument, adapter):
    items = [i.model_copy(update={"required": False}) for i in instrument.items]
    config = instrument.model_copy(update={"items": tuple(items)})
    svc = make_service(config, adapter)
    view = consent(svc)
    for _ in range(13):
        req = {**request(view), "answer_value": None, "missing_reason": "prefer_not_to_answer"}
        view = svc.answer(view["session_id"], req)["current"]
    snap = svc.repo.read(view["session_id"])
    assert snap.session["state"]["observed_state"] == {}
    req = {**request(view), "answer_value": None, "missing_reason": "skip"}
    svc.answer(view["session_id"], req)
    snap = svc.repo.read(view["session_id"])
    assert snap.session["state"]["observed_state"] == {}
    assert len(snap.session["state"]["asked_ids"]) == 14


def test_integrity_and_big_rng_roundtrip(instrument, adapter):
    from human_study.policy import initial_rng
    state = initial_rng(2**127)
    assert decode(encode(state)) == state
    archive = MemoryArchive()
    archive.put("same", {"x": 1})
    archive.put("same", {"x": 1})
    with pytest.raises(IntegrityError):
        archive.put("same", {"x": 2})


def test_changed_instrument_does_not_reinterpret_session(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    changed = instrument.model_copy(update={"consent_version": "different"})
    restarted = make_service(changed, adapter, svc.repo, svc.archive)
    with pytest.raises(Conflict, match="different instrument"):
        restarted.current(view["session_id"])


def test_concurrent_generation_is_claimed_once(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    for _ in range(12):
        view = svc.answer(view["session_id"], request(view))["current"]
    started, release = threading.Event(), threading.Event()
    original = svc.llm.generate
    def slow(item):
        started.set()
        assert release.wait(5)
        return original(item)
    svc.llm.generate = slow
    sid = view["session_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        answer = pool.submit(svc.answer, sid, request(view))
        assert started.wait(5)
        with pytest.raises(GenerationPending):
            svc.current(sid)
        release.set()
        final = answer.result()
    assert svc.llm.calls == 1
    assert svc.current(sid)["question"] == final["current"]["question"]


def test_final_archive_failure_never_exposes_receipt(instrument, adapter):
    svc = make_service(instrument, adapter)
    view = consent(svc)
    while view["phase"] != "ready_to_complete":
        view = svc.answer(view["session_id"], request(view))["current"]
    sid = view["session_id"]
    real_put = svc.archive.put
    def fail_final(name, payload):
        if name.endswith("/final.json"):
            raise OSError("GCS failed")
        real_put(name, payload)
    svc.archive.put = fail_final
    with pytest.raises(ExportPending):
        svc.complete(sid)
    snap = svc.repo.read(sid)
    assert snap.session["receipt"] and svc.public(snap)["receipt"] is None
    assert not any(n.endswith("/final.json") for n in svc.archive.objects)
    svc.archive.put = real_put
    assert svc.complete(sid)["receipt"] == snap.session["receipt"]


def test_research_csv_export_contract(instrument, adapter, tmp_path):
    import csv
    from human_study.export import export_records
    svc = make_service(instrument, adapter)
    view = finish(svc, consent(svc))
    name = f"studies/{instrument.study_id}/sessions/{view['session_id']}/final.json"
    export_records([(name, json.loads(svc.archive.objects[name]))], tmp_path / "export")
    assert {p.name for p in (tmp_path / "export").iterdir()} == {
        "participants.csv", "baseline.csv", "questions.csv", "answers.csv", "trajectories.csv", "outcomes.csv", "provenance.json"}
    with (tmp_path / "export/trajectories.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 20 and all(r["predicted_model_delta"] and r["observed_conditional_index_delta"] for r in rows)
