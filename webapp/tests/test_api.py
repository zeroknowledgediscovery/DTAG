"""HTTP API contract tests (fake native backend, mock LLM)."""
from __future__ import annotations

import csv
import io
import json

from dtag_web.schemas import QuestionResult, SessionOut


def test_health_has_no_secrets(fake_client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    r = fake_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    for k in ("status", "dtag_version", "native_runtime", "openai_configured", "model_release", "model_cache_root", "models_loaded"):
        assert k in body
    assert body["native_runtime"] == "bundled_persistent" and body["openai_configured"] is True
    assert "sk-test-secret-value" not in r.text


def test_readiness_distinguishes_catalog_profiles_installed_loaded(fake_client):
    body = fake_client.get("/api/readiness").json()
    assert body["public_catalog"]["models"] == 6  # fake manifest
    assert body["configured_profiles"]["count"] >= 9
    assert body["model_cache"]["installed"] == 1
    assert body["models_resident"]["loaded"] == 0
    assert body["semantic_maps"]["maps"] >= 252


def test_profiles_and_models(fake_client):
    profiles = fake_client.get("/api/profiles").json()
    names = {p["name"] for p in profiles}
    assert {"gss2024_cm", "wvs7_india_2017", "afrobarometer_r5_nigeria"} <= names
    p = fake_client.get("/api/profiles/gss2024_cm").json()
    assert p["model_key"] == "gss/gss_2024" and "allowed_overrides" in p
    assert fake_client.get("/api/profiles/nope").status_code == 404
    models = fake_client.get("/api/models").json()
    rec = next(m for m in models if m["key"] == "gss/gss_2024")
    for k in ("key", "family", "name", "installed", "loaded", "map_available", "ideology_available", "archive_bytes", "release"):
        assert k in rec
    assert fake_client.get("/api/models/gss/gss_2024").json()["installed"] is True
    assert fake_client.get("/api/models/gss/..%2F..%2Fetc").status_code in (400, 404)


def test_session_lifecycle(fake_client):
    r = fake_client.post("/api/sessions", json={"profile": "gss2024_cm", "overrides": {"resp_mode": "max"}})
    assert r.status_code == 200, r.text
    s = SessionOut.model_validate(r.json())
    assert s.ideology["enabled"] and s.initial_state == s.current_state
    sid = s.session_id

    q = fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Which statement about immigrants matches your view?"})
    assert q.status_code == 200, q.text
    res = QuestionResult.model_validate(q.json())
    assert res.mapping.label == "DIRECT" and res.anchors and res.timings["native_predict"] >= 0
    assert "qnet_predict" not in res.timings
    assert res.geographic_conditioning["conditioning_mode"] == "survey_context_only"

    q2 = fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "[nomatch] favourite colour?"}).json()
    assert q2["mapping"]["label"] == "NO MATCH" and q2["state_changed"] is False

    got = fake_client.get(f"/api/sessions/{sid}").json()
    assert got["question_count"] == 2 and len(got["history"]) == 2
    assert [p["step"] for p in got["ideology"]["trajectory"]] == [0, 1, 2]

    ex = fake_client.get(f"/api/sessions/{sid}/export?format=json")
    assert ex.status_code == 200 and "attachment" in ex.headers["content-disposition"]
    data = ex.json()
    assert data["model"]["key"] == "gss/gss_2024" and len(data["questions"]) == 2
    rows = list(csv.DictReader(io.StringIO(fake_client.get(f"/api/sessions/{sid}/export?format=csv").text)))
    assert [r["mapping"] for r in rows] == ["DIRECT", "NO MATCH"]
    assert json.loads(rows[0]["anchors"])

    reset = fake_client.post(f"/api/sessions/{sid}/reset").json()
    assert reset["question_count"] == 0 and reset["current_state"] == reset["initial_state"]

    assert fake_client.delete(f"/api/sessions/{sid}").status_code == 200
    assert fake_client.get(f"/api/sessions/{sid}").status_code == 404


def test_rejects_unsafe_or_invalid_input(fake_client):
    bad = [
        {"profile": "gss2024_cm", "overrides": {"map_key": "../../etc/passwd.csv"}},
        {"profile": "gss2024_cm", "overrides": {"cli_args": "--qnet /etc"}},
        {"profile": "gss2024_cm", "overrides": {"semantic_fallback": "always"}},
        {"profile": "gss2024_cm", "overrides": {"model_key": "http://evil/x"}},
        {"profile": "../gss2024_cm"},
        {"profile": "wvs7_india_2017", "overrides": {"polar_set": "gss_default"}},
    ]
    for body in bad:
        r = fake_client.post("/api/sessions", json=body)
        assert r.status_code in (400, 422), (body, r.status_code, r.text)
    r = fake_client.post("/api/sessions/deadbeef/questions", json={"question": "hi"})
    assert r.status_code == 404
    assert fake_client.post("/api/sessions", json={"profile": "gss2024_cm"}).status_code == 200


def test_custom_profile_api(fake_client):
    r = fake_client.post("/api/profiles/validate", json={"base_profile": "gss2024_cm", "overrides": {"year": 2022}})
    assert r.status_code == 200 and r.json()["model_key"] == "gss/gss_2022"
    r = fake_client.post("/api/profiles", json={"name": "api_custom", "base_profile": "gss2024_cm", "overrides": {"persona": "p"}})
    assert r.status_code == 200 and r.json()["source"] == "custom"
    assert "api_custom" in {p["name"] for p in fake_client.get("/api/profiles").json()}
    assert fake_client.delete("/api/profiles/gss2024_cm").status_code == 400
    assert fake_client.delete("/api/profiles/api_custom").status_code == 200


def test_eurobarometer_endpoints(fake_client):
    w = fake_client.get("/api/eurobarometer/waves").json()
    if not w["date_registry_available"]:
        return
    assert any(x["za"] == "ZA7575" and x["model_key"] == "eurobarometer/ZA7575_v1-0-0" for x in w["waves"])
    r = fake_client.get("/api/eurobarometer/resolve?date=2019-05-15").json()
    assert r["resolved_za"] == "ZA7575" and r["temporal"]["fieldwork"]["fieldwork_end"] == "2019-05-25"
    assert fake_client.get("/api/eurobarometer/resolve?year=2019").status_code == 400


def test_openapi_docs_available(fake_client):
    assert fake_client.get("/docs").status_code == 200
    spec = fake_client.get("/openapi.json").json()
    assert "/api/sessions/{session_id}/questions" in spec["paths"]


def test_session_requires_llm(fake_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from pathlib import Path
    from dtag_web.app import create_app

    fake_engine.llm_backend = "openai"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app(engine=fake_engine, frontend_dist=Path("/nonexistent")))
    r = client.post("/api/sessions", json={"profile": "gss2024_cm"})
    assert r.status_code == 400 and "OPENAI_API_KEY" in r.json()["detail"]
