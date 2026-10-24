import json

import pytest
from fastapi.testclient import TestClient

from human_study.app import create_app, configured_service
from human_study.service import StudyService
from human_study.storage import MemoryRepository, MemoryArchive
from human_study.local_fixture import LocalLLM as FixtureLLM


def client(config, adapter):
    service = StudyService(config, adapter, FixtureLLM(), MemoryRepository(), MemoryArchive())
    app = create_app(service, cookie_secret="test-secret-stable-not-for-deployment" * 2)
    return TestClient(app), service


def post(c, route, payload):
    return c.post("/api/human/" + route, json=payload, headers={"Origin": "http://testserver"})


def test_anonymous_isolation_and_no_public_debug_routes(instrument, adapter):
    a, svc = client(instrument, adapter)
    b = TestClient(a.app)
    with a, b:
        assert a.get("/api/human/health").json() == {"status": "ok"}
        va = post(a, "start", {}).json()
        vb = post(b, "start", {}).json()
        assert va["session_id"] != vb["session_id"]
        a1 = post(a, "consent", {"accepted": True, "expected_session_version": va["session_version"]}).json()
        b1 = post(b, "consent", {"accepted": True, "expected_session_version": vb["session_version"]}).json()
        payload = {"question_id": a1["question"]["question_id"], "answer_value": "yes",
                   "idempotency_key": "unique-key", "expected_session_version": b1["session_version"]}
        assert post(b, "answer", payload).status_code == 409
        assert post(a, "answer", {**payload, "expected_session_version": a1["session_version"]}).status_code == 200
        assert svc.repo.read(vb["session_id"]).session["next_step"] == 0
        for path in ("/docs", "/redoc", "/openapi.json", "/api/sessions", "/api/profiles", "/api/models"):
            assert a.get(path).status_code == 404
        assert b.get("/api/human/receipt").status_code == 409
        cookie = next(iter(a.cookies.values()))
        b.cookies.clear()
        b.cookies.set("dtag-human-local", cookie + "tampered")
        assert b.get("/api/human/current").status_code == 401


def test_input_csrf_size_and_public_whitelist(instrument, adapter):
    c, _ = client(instrument, adapter)
    with c:
        assert c.post("/api/human/start", json={}).status_code == 403
        assert post(c, "start", {"policy": "right"}).status_code == 422
        assert post(c, "start", {"PROLIFIC_PID": "not-authentication"}).status_code == 422
        assert post(c, "start", {"data": "a" * 5000}).status_code == 413
        view = post(c, "start", {}).json()
        response = post(c, "consent", {"accepted": True, "expected_session_version": view["session_version"]})
        assert response.status_code == 200
        assert "HttpOnly" in post(c, "start", {}).headers["set-cookie"]
        assert response.headers["Cache-Control"] == "no-store"


def test_cloud_run_https_origin_with_internal_http_scope(monkeypatch, instrument, adapter):
    # Cloud Run terminates HTTPS and forwards HTTP to the application. The
    # participant's browser Origin must still match the external HTTPS host.
    monkeypatch.setenv("DTAG_ENV", "staging")
    service = StudyService(instrument, adapter, FixtureLLM(), MemoryRepository(), MemoryArchive())
    app = create_app(service, cookie_secret="test-secret-stable-not-for-deployment" * 2)
    # No lifespan context: isolates the origin middleware without connecting
    # the test fixture to production-only Firestore/GCS readiness checks.
    c = TestClient(app, base_url="http://testserver")

    route = "/api/human/start"
    assert c.post(route, json={}).status_code == 403
    assert c.post(route, json={}, headers={"Origin": "http://testserver"}).status_code == 403
    assert c.post(route, json={}, headers={"Origin": "https://attacker.example"}).status_code == 403
    # Do not honor untrusted proxy headers when authorizing browser writes.
    assert c.post(route, json={}, headers={
        "Origin": "http://testserver", "X-Forwarded-Proto": "http",
    }).status_code == 403
    ok = c.post(route, json={}, headers={
        "Origin": "https://testserver", "X-Forwarded-Proto": "http",
    })
    assert ok.status_code == 200
    assert ok.json()["phase"] == "consent"
    assert "Secure" in ok.headers["set-cookie"]


def test_unavailable_llm_never_exposes_incomplete_baseline_source(instrument, adapter):
    # A baseline source fragment is generated via LLM, never shown verbatim.
    first = instrument.items[0].model_copy(update={
        "original_wording": "This original question is truncated at the",
        "source_text_incomplete": True,
    })
    config = instrument.model_copy(update={"items": (first, *instrument.items[1:])})

    class OfflineLLM:
        def generate(self, item):
            raise RuntimeError("provider unavailable")

    svc = StudyService(config, adapter, OfflineLLM(), MemoryRepository(), MemoryArchive())
    web = TestClient(create_app(svc, cookie_secret="test-secret-stable-not-for-deployment" * 2))
    with web:
        start = post(web, "start", {}).json()
        response = post(web, "consent", {
            "accepted": True, "expected_session_version": start["session_version"]})
        assert response.status_code == 503
        assert response.json()["status"] == "preparing_question"
        snapshot = svc.repo.read(start["session_id"])
        questions = [v for k, v in snapshot.records.items() if k.startswith("questions/")]
        assert len(questions) == 1
        assert questions[0]["status"] == "generating"
        assert questions[0]["generation_failure_count"] == 1
        assert "displayed_wording" not in questions[0]


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_fail_closed_nonlocal_fixture_and_missing_secrets(monkeypatch, mode):
    monkeypatch.setenv("DTAG_ENV", mode)
    monkeypatch.delenv("DTAG_COOKIE_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="secret"):
        create_app()
    monkeypatch.setenv("DTAG_LOCAL_FIXTURE", "1")
    monkeypatch.setenv("DTAG_LLM_BACKEND", "mock")
    with pytest.raises(RuntimeError, match="restricted"):
        configured_service()
