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
