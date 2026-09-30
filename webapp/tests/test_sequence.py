"""Question sequences through one respondent (fake native backend, mock LLM)."""
from __future__ import annotations

import time

import pytest

from dtag_web.sequences import parse_question_lines

QS = [
    "Which statement about immigrants matches your view?",
    "Do you think of yourself as liberal or conservative?",
    "[nomatch] What is your favourite colour?",
    "Do you favor or oppose gun permits?",
]


def _wait(client, sid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/api/sessions/{sid}/sequence").json()
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(0.05)
    raise AssertionError("sequence did not finish")


def _session(client, profile="gss2024_cm"):
    return client.post("/api/sessions", json={"profile": profile}).json()["session_id"]


def test_parse_question_lines():
    text = "question\nFirst?\n\n# a comment\n  Second?  \n\"Third, with comma?\"\n"
    assert parse_question_lines(text) == ["First?", "Second?", "Third, with comma?"]
    assert parse_question_lines("Only one") == ["Only one"]
    assert parse_question_lines("\n\n") == []


def test_sequence_runs_in_order_and_tracks_ideology(fake_client):
    sid = _session(fake_client)
    start = fake_client.get(f"/api/sessions/{sid}").json()["ideology"]["current"]
    r = fake_client.post(f"/api/sessions/{sid}/sequence", json={"text": "\n".join(QS), "name": "demo"})
    assert r.status_code == 200 and r.json()["total"] == 4
    s = _wait(fake_client, sid)
    assert s["status"] == "done" and s["completed"] == 4 and s["name"] == "demo"
    assert [x["question"] for x in s["results"]] == QS
    assert [x["query_idx"] for x in s["results"]] == [1, 2, 3, 4]
    assert s["results"][2]["mapping"]["label"] == "NO MATCH"
    ide = s["ideology"]
    assert ide["enabled"] and ide["start"] == pytest.approx(start)
    assert ide["end"] == pytest.approx(s["results"][-1]["ideology"]["after"])
    assert ide["net_change"] == pytest.approx(ide["end"] - ide["start"])
    assert ide["min"] <= ide["start"] <= ide["max"]
    assert all(m["delta"] for m in ide["top_movers"])
    # state carried forward: the session now has 4 questions and a 5-point trajectory
    sess = fake_client.get(f"/api/sessions/{sid}").json()
    assert sess["question_count"] == 4 and len(sess["ideology"]["trajectory"]) == 5
    # incremental polling
    assert fake_client.get(f"/api/sessions/{sid}/sequence?since=3").json()["results"][0]["query_idx"] == 4


def test_sequence_continues_from_current_state_or_resets(fake_client):
    sid = _session(fake_client)
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": QS[0]})
    fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": QS[1:2]})
    s = _wait(fake_client, sid)
    assert s["first_query_idx"] == 2 and s["results"][0]["query_idx"] == 2
    fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": QS[1:2], "reset_first": True})
    s = _wait(fake_client, sid)
    assert s["first_query_idx"] == 1
    assert fake_client.get(f"/api/sessions/{sid}").json()["question_count"] == 1


def test_sequence_without_ideology(fake_client):
    sid = fake_client.post("/api/sessions", json={"profile": "gss2024_cm", "overrides": {"ideology": False}}).json()["session_id"]
    fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": QS[:2]})
    s = _wait(fake_client, sid)
    assert s["status"] == "done" and not s["ideology"]["enabled"] and s["ideology"]["net_change"] is None


def test_sequence_validation_and_conflicts(fake_client, monkeypatch):
    sid = _session(fake_client)
    assert fake_client.post(f"/api/sessions/{sid}/sequence", json={"text": "\n# only comments\n"}).status_code == 400
    assert fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": ["x"] * 501}).status_code in (400, 422)
    assert fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": ["x" * 2001]}).status_code == 400
    assert fake_client.get(f"/api/sessions/{sid}/sequence").status_code == 404
    assert fake_client.post("/api/sessions/nope/sequence", json={"questions": ["x"]}).status_code == 404

    # slow down answering so the job is observably running
    es = fake_client.app.state.sessions.get(sid)
    orig = es.ask

    def slow(q):
        time.sleep(0.2)
        return orig(q)

    monkeypatch.setattr(es, "ask", slow)
    fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": QS * 5})
    assert fake_client.post(f"/api/sessions/{sid}/sequence", json={"questions": QS}).status_code == 409
    assert fake_client.post(f"/api/sessions/{sid}/questions", json={"question": QS[0]}).status_code == 409
    assert fake_client.post(f"/api/sessions/{sid}/reset").status_code == 409
    assert fake_client.delete(f"/api/sessions/{sid}/sequence").status_code == 200
    s = _wait(fake_client, sid)
    assert s["status"] == "cancelled" and 0 < s["completed"] < 20
    # interactive questions work again after cancel
    assert fake_client.post(f"/api/sessions/{sid}/questions", json={"question": QS[0]}).status_code == 200
