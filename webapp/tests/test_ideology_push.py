"""Ideology push: one-step up/down question suggestions, targeted asks and auto-push."""
from __future__ import annotations

import time

import pytest


def _session(client, **overrides):
    r = client.post("/api/sessions", json={"profile": "gss2024_cm", "overrides": overrides})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _wait(client, sid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/sessions/{sid}/sequence").json()
        if st["status"] not in ("queued", "running"):
            return st
        time.sleep(0.05)
    raise AssertionError("auto-push did not finish")


def test_suggestions_and_targeted_ask(fake_client):
    sid = _session(fake_client, resp_mode="max")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true").json()
    assert sug["enabled"] and sug["objective"] == "modal" and sug["n_candidates"] > 0
    state = fake_client.get(f"/api/sessions/{sid}").json()["current_state"]
    picks = [d for d in ("up", "down") if sug[d]]
    assert picks, sug
    for d in picks:
        s = sug[d]
        assert s["variable"] not in state and s["question"]
        assert (s["predicted_delta"] > 0) if d == "up" else (s["predicted_delta"] < 0)
        assert s["predicted_delta"] == s["delta_modal"]
        assert abs(sum(a["p"] for a in s["responses"]) - 1) < 1e-9
    for d in ("up", "down"):
        if not sug[d]:
            assert sug[f"{d}_reason"]

    assert sug["mode"] == "realistic" and all(sug[d]["mapped_variables"] is None for d in picks)

    # Realistic (default): the question goes through the normal mapping like a typed question.
    s = sug[picks[0]]
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/ask",
                         json={"variable": s["variable"], "question": s["question"], "direction": picks[0]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["targeted"] is False and res["question_source"] == "ideology_push"
    push = res["push"]
    assert push["mode"] == "realistic" and push["mapped_variables"] == res["selected_variables"]
    assert push["hit"] == (s["variable"] in res["selected_variables"])
    assert push["realized_delta"] == pytest.approx(res["ideology"]["delta"], abs=1e-12)
    traj = fake_client.get(f"/api/sessions/{sid}").json()["ideology"]["trajectory"]
    assert len(traj) == 2


def test_validated_mode_maps_back_and_is_exact(fake_client):
    sid = _session(fake_client, resp_mode="max")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true&mode=validated").json()
    assert sug["mode"] == "validated"
    picks = [d for d in ("up", "down") if sug[d]]
    for d in ("up", "down"):
        assert sug[f"{d}_checked"] is not None or sug[f"{d}_reason"]
        if not sug[d]:
            assert sug[f"{d}_reason"]
    assert picks, sug
    d = picks[0]
    s = sug[d]
    assert s["variable"] in s["mapped_variables"] and s["exact"] in (True, False)
    assert (s["predicted_delta"] > 0) if d == "up" else (s["predicted_delta"] < 0)
    assert any(c["hit"] and c["variable"] == s["variable"] for c in sug[f"{d}_checked"])
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/ask",
                         json={"variable": s["variable"], "question": s["question"], "direction": d,
                               "mode": "validated"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["targeted"] is True and res["selected_variables"] == s["mapped_variables"]
    assert res["push"]["hit"] is True and res["push"]["mode"] == "validated"
    assert res["push"]["realized_delta"] == pytest.approx(s["predicted_delta"], abs=1e-12)
    assert res["push"]["predicted_joint_delta"] == pytest.approx(s["predicted_delta"], abs=1e-12)


def test_validated_ask_rejects_question_that_misses_item(fake_client):
    sid = _session(fake_client, resp_mode="max")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true").json()
    s = sug["up"] or sug["down"]
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/ask",
                         json={"variable": s["variable"], "question": "zzqx unrelated wording", "mode": "validated"})
    assert r.status_code == 400


def test_targeted_ask_rejects_unknown_item(fake_client):
    sid = _session(fake_client)
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/ask", json={"variable": "no_such_item", "question": "Q?"})
    assert r.status_code == 400


def test_draw_mode_ranks_by_expected_change(fake_client):
    sid = _session(fake_client, resp_mode="draw")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true").json()
    assert sug["objective"] == "expected"
    for d in ("up", "down"):
        if sug[d]:
            assert sug[d]["predicted_delta"] == sug[d]["expected_delta"]


def test_auto_push_runs_steps_and_records_trajectory(fake_client):
    sid = _session(fake_client, resp_mode="max")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true").json()
    direction = "up" if sug["up"] else "down"
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/auto",
                         json={"direction": direction, "steps": 3, "include_pole_items": True})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "ideology_push" and r.json()["direction"] == direction
    st = _wait(fake_client, sid)
    assert st["status"] == "done", st
    assert 1 <= st["completed"] <= 3 and len(st["predictions"]) == st["completed"]
    assert st["mode"] == "realistic"
    for p, res in zip(st["predictions"], st["results"]):
        assert res["push"]["direction"] == direction and res["push"]["mode"] == "realistic"
        assert res["push"]["mapped_variables"] == res["selected_variables"]
    if st["completed"] < 3:
        assert st["stop_reason"]
    info = fake_client.get(f"/api/sessions/{sid}").json()
    assert info["question_count"] == st["completed"] and len(info["ideology"]["trajectory"]) == st["completed"] + 1


def test_auto_push_validated_is_exact(fake_client):
    sid = _session(fake_client, resp_mode="max")
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/auto",
                         json={"direction": "up", "steps": 2, "include_pole_items": True, "mode": "validated"})
    assert r.status_code == 200, r.text
    st = _wait(fake_client, sid)
    assert st["status"] == "done" and st["mode"] == "validated", st
    for p, res in zip(st["predictions"], st["results"]):
        assert res["selected_variables"] == p["mapped_variables"] and p["variable"] in p["mapped_variables"]
        assert res["ideology"]["delta"] == pytest.approx(p["predicted_delta"], abs=1e-12)


def test_no_ideology_survey_reports_disabled(fake_client):
    sid = _session(fake_client, ideology=False)
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push").json()
    assert sug["enabled"] is False and sug["reason"] and sug["up"] is None and sug["down"] is None
    auto = fake_client.post(f"/api/sessions/{sid}/ideology-push/auto", json={"direction": "up", "steps": 2})
    assert auto.status_code == 409


@pytest.mark.native
def test_native_push_prediction_is_exact(native_engine):
    from conftest import NATIVE_KEY
    if not NATIVE_KEY.startswith("gss/"):
        pytest.skip("ideology poles are GSS-specific")
    year = NATIVE_KEY.rsplit("_", 1)[-1]
    spec = native_engine.build_spec(profile=f"gss{year}_cm", overrides={"resp_mode": "max"})
    es = native_engine.create_session(spec=spec)
    sug = native_engine.ideology_push(es)
    assert sug["enabled"] and sug["fast_evaluator"] and sug["n_candidates"] > 100
    assert sug["current_ideology"] == pytest.approx(es.ideology_summary()["current"], abs=1e-12)
    for d in ("up", "down"):
        s = sug[d]
        if s is None:
            continue
        before = es.ideology_summary()["current"]
        r = es.ask_targeted(s["question"], s["variable"], direction=d)
        assert r["selected_variables"] == [s["variable"]]
        assert r["ideology"]["after"] - before == pytest.approx(r["push"]["predicted_modal_delta"], abs=1e-12)
        sug = native_engine.ideology_push(es)


@pytest.mark.native
def test_native_validated_push_is_exact(native_engine):
    from conftest import NATIVE_KEY
    if not NATIVE_KEY.startswith("gss/"):
        pytest.skip("ideology poles are GSS-specific")
    year = NATIVE_KEY.rsplit("_", 1)[-1]
    spec = native_engine.build_spec(profile=f"gss{year}_cm", overrides={"resp_mode": "max"})
    es = native_engine.create_session(spec=spec)
    sug = native_engine.ideology_push(es, mode="validated")
    for d in ("up", "down"):
        s = sug[d]
        if s is None:
            assert sug[f"{d}_reason"]
            continue
        assert s["variable"] in s["mapped_variables"]
        r = es.ask_push(s["question"], s["variable"], direction=d, mode="validated")
        assert r["selected_variables"] == s["mapped_variables"] and r["push"]["hit"]
        assert r["push"]["realized_delta"] == pytest.approx(s["predicted_delta"], abs=1e-12)
        sug = native_engine.ideology_push(es, mode="validated")


def test_direct_mode_answers_through_exactly_the_item(fake_client):
    sid = _session(fake_client, resp_mode="max")
    sug = fake_client.get(f"/api/sessions/{sid}/ideology-push?include_pole_items=true&mode=direct").json()
    assert sug["mode"] == "direct"
    d = "up" if sug["up"] else "down"
    s = sug[d]
    r = fake_client.post(f"/api/sessions/{sid}/ideology-push/ask",
                         json={"variable": s["variable"], "question": s["question"], "direction": d, "mode": "direct"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["targeted"] is True and res["selected_variables"] == [s["variable"]]
    assert res["push"]["mode"] == "direct" and res["push"]["hit"] is True
    assert res["push"]["realized_delta"] == pytest.approx(s["predicted_delta"], abs=1e-12)
    auto = fake_client.post(f"/api/sessions/{sid}/ideology-push/auto",
                            json={"direction": d, "steps": 2, "include_pole_items": True, "mode": "direct"})
    assert auto.status_code == 200, auto.text
    st = _wait(fake_client, sid)
    assert st["status"] == "done" and st["mode"] == "direct"
    for p, res in zip(st["predictions"], st["results"]):
        assert res["selected_variables"] == [p["variable"]]
        assert res["ideology"]["delta"] == pytest.approx(p["predicted_delta"], abs=1e-12)
