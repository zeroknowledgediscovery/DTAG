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


def test_configured_public_origin_survives_proxy_host_rewriting(monkeypatch, instrument, adapter):
    monkeypatch.setenv("DTAG_ENV", "staging")
    public = "https://dtag-human-pilot-75214764470.us-east1.run.app"
    monkeypatch.setenv("DTAG_PUBLIC_ORIGIN", public)
    service = StudyService(instrument, adapter, FixtureLLM(), MemoryRepository(), MemoryArchive())
    app = create_app(service, cookie_secret="test-secret-stable-not-for-deployment" * 2)
    # The externally visible Host may be replaced by an internal proxy host,
    # while the browser Origin is still the true service URL.
    c = TestClient(app, base_url="http://internal-proxy:8080")
    route = "/api/human/start"
    assert c.post(route, json={}, headers={"Origin": "https://attacker.example"}).status_code == 403
    assert c.post(route, json={}, headers={"Origin": "http://internal-proxy:8080"}).status_code == 403
    assert c.post(route, json={}, headers={"Origin": "https://internal-proxy:8080"}).status_code == 403
    valid = c.post(route, json={}, headers={"Origin": public})
    assert valid.status_code == 200
    assert valid.json()["phase"] == "consent"
    assert "Secure" in valid.headers["set-cookie"]


def test_public_origin_must_be_exact_https(monkeypatch, instrument, adapter):
    monkeypatch.setenv("DTAG_ENV", "staging")
    svc = StudyService(instrument, adapter, FixtureLLM(), MemoryRepository(), MemoryArchive())
    for origin in ("http://study.example", "https://study.example/study",
                   "https://study.example/", "https://user@study.example"):
        monkeypatch.setenv("DTAG_PUBLIC_ORIGIN", origin)
        with pytest.raises(RuntimeError, match="DTAG_PUBLIC_ORIGIN"):
            create_app(svc, cookie_secret="test-secret-stable-not-for-deployment" * 2)


def test_immutable_manifest_survives_deploy_revisions_and_restart(monkeypatch, instrument, adapter):
    # Regression for Cloud Run startup failure: same instrument, different
    # code provenance must never target the same immutable GCS object.
    from copy import copy
    from human_study.app import study_manifest
    monkeypatch.setenv("DTAG_ENV", "staging")
    monkeypatch.delenv("DTAG_PUBLIC_ORIGIN", raising=False)

    class DurableRepo(MemoryRepository):
        durable = True

    class DurableArchive(MemoryArchive):
        durable = True

    shared = DurableArchive()
    for sha in ("a" * 40, "a" * 40, "b" * 40):
        inst_adapter = copy(adapter)
        inst_adapter.provenance = {"model_content_sha256": "unchanged-native-model",
                                   "code_commit": sha}
        key, payload = study_manifest(instrument, inst_adapter.provenance)
        assert key.startswith(f"studies/{instrument.study_id}/manifests/{instrument.config_hash}-")
        service = StudyService(instrument, inst_adapter, FixtureLLM(), DurableRepo(), shared)
        app = create_app(service, cookie_secret="test-secret-stable-not-for-deployment" * 2)
        with TestClient(app) as client:
            assert client.get("/api/human/health").json() == {"status": "ok"}
        assert shared.objects[key]  # The payload was stored immutably.
    # Duplicate starts are idempotent, while distinct code commits remain
    # separate objects with their original content preserved.
    assert len(shared.objects) == 2
    contents = sorted(__import__("json").loads(x)["provenance"]["code_commit"]
                      for x in shared.objects.values())
    assert contents == ["a" * 40, "b" * 40]


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



def test_new_session_preserves_previous_progress_and_signed_resume(instrument, adapter):
    c, svc = client(instrument, adapter)
    with c:
        first = post(c, "start", {}).json()
        view = post(c, "consent", {
            "accepted": True,
            "expected_session_version": first["session_version"],
        }).json()
        answer = post(c, "answer", {
            "question_id": view["question"]["question_id"],
            "answer_value": view["question"]["choices"][0]["value"],
            "idempotency_key": "first-answered-before-restart",
            "expected_session_version": view["session_version"],
        })
        assert answer.status_code == 200, answer.text
        previous = post(c, "start", {}).json()
        assert previous["session_id"] == first["session_id"]
        assert previous["progress"]["completed"] == 1
        prior_archive = dict(svc.archive.objects)
        cookie_before = c.cookies.get("dtag-human-local")

        fresh_response = post(c, "restart", {})
        assert fresh_response.status_code == 200, fresh_response.text
        fresh = fresh_response.json()
        assert fresh["session_id"] != first["session_id"]
        assert fresh["phase"] == "consent"
        assert fresh["progress"]["completed"] == 0
        assert c.cookies.get("dtag-human-local") != cookie_before
        assert svc.repo.read(first["session_id"]).session["next_step"] == 1
        assert prior_archive.items() <= svc.archive.objects.items()
        assert c.get("/api/human/current").json()["session_id"] == fresh["session_id"]
        assert post(c, "start", {}).json()["session_id"] == fresh["session_id"]


def test_restart_requires_origin_valid_start_body_and_rate_limit(instrument, adapter):
    c, svc = client(instrument, adapter)
    with c:
        original = post(c, "start", {}).json()["session_id"]
        assert c.post("/api/human/restart", json={}).status_code == 403
        assert post(c, "restart", {"force": True}).status_code == 422
        assert c.get("/api/human/current").json()["session_id"] == original
        restarted = []
        # One enrollment already occurred through /start; quota of 10/min.
        for n in range(9):
            response = post(c, "restart", {})
            assert response.status_code == 200, (n, response.text)
            restarted.append(response.json()["session_id"])
        assert len(set(restarted)) == 9
        blocked = post(c, "restart", {})
        assert blocked.status_code == 429
        assert c.get("/api/human/current").json()["session_id"] == restarted[-1]


def test_stale_code_cookie_can_start_new_session_without_losing_old_data(instrument, adapter):
    repo = MemoryRepository()
    archive = MemoryArchive()
    secret = "test-secret-stable-not-for-deployment" * 2
    old = StudyService(instrument, adapter, FixtureLLM(), repo, archive)
    first_client = TestClient(create_app(old, cookie_secret=secret))
    with first_client:
        first = post(first_client, "start", {}).json()
        old_sid = first["session_id"]
        cookie = first_client.cookies.get("dtag-human-local")
        assert cookie

    new_config = instrument.model_copy(update={"consent_version": "new-revision-test"})
    new = StudyService(new_config, adapter, FixtureLLM(), repo, archive)
    second_client = TestClient(create_app(new, cookie_secret=secret))
    second_client.cookies.set("dtag-human-local", cookie)
    with second_client:
        assert post(second_client, "start", {}).status_code == 409
        result = post(second_client, "restart", {})
        assert result.status_code == 200, result.text
        fresh = result.json()
        assert fresh["session_id"] != old_sid
        assert fresh["phase"] == "consent"
        assert post(second_client, "start", {}).json()["session_id"] == fresh["session_id"]
    assert repo.read(old_sid).session["config_hash"] == instrument.config_hash


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_restart_has_same_behavior_in_staging_and_production(monkeypatch, instrument, adapter, mode):
    monkeypatch.setenv("DTAG_ENV", mode)
    service = StudyService(instrument, adapter, FixtureLLM(), MemoryRepository(), MemoryArchive())
    # Nonlocal deployments use __Host- prefixed Secure cookies. The browser
    # MUST use HTTPS: a Secure cookie is deliberately not sent over HTTP.
    # The old TestClient defaulted to http://testserver but supplied an HTTPS
    # Origin header. That satisfied CSRF checks without sending the cookie,
    # causing a false restart/resumption failure in both modes.
    web = TestClient(create_app(
        service, cookie_secret="test-secret-stable-not-for-deployment" * 2
    ), base_url="https://testserver")
    headers = {"Origin": "https://testserver"}
    with web:
        first = web.post("/api/human/start", json={}, headers=headers)
        assert first.status_code == 200, first.text
        assert "Secure" in first.headers["set-cookie"]
        assert web.cookies.get("__Host-dtag-human")

        fresh_response = web.post("/api/human/restart", json={}, headers=headers)
        assert fresh_response.status_code == 200, fresh_response.text
        assert "Secure" in fresh_response.headers["set-cookie"]
        fresh = fresh_response.json()
        assert fresh["phase"] == "consent"
        assert fresh["session_id"] != first.json()["session_id"]
        assert web.get("/api/human/current").json()["session_id"] == fresh["session_id"]
        resumed = web.post("/api/human/start", json={}, headers=headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["session_id"] == fresh["session_id"]
        assert len(service.repo.sessions) == 2
