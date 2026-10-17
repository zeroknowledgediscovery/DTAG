"""Decision landscape: predicted answers to every askable item, and how interactions move them."""
from __future__ import annotations

import math

import pytest


def _session(client, **overrides):
    r = client.post("/api/sessions", json={"profile": "gss2024_cm", "overrides": overrides})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_topics_and_divergence(fake_client):
    from optimizer.landscape import js_divergence  # importable once the app put the repo on sys.path
    from optimizer.topics import ORDER, topic_of

    assert topic_of("CONFIDENCE IN CHURCHES AND RELIGIOUS ORGS") == "Trust & confidence"
    assert topic_of("NOT MARRIED", "absingle") == "Abortion & sexuality"
    assert topic_of("AGE OF 4TH PERSON", "OLD4") == "Background"
    assert topic_of("zzz") == "Other" and ORDER[-2:] == ["Other", "Background"]
    assert js_divergence({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0
    assert js_divergence({"a": 1.0}, {"b": 1.0}) == pytest.approx(1.0)


def test_landscape_tracks_interactions(fake_client):
    sid = _session(fake_client, resp_mode="max")
    v0 = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert v0["enabled"] and v0["step"] == 0 and v0["since_step"] is None and v0["has_lean"]
    assert v0["items"] and all(0 <= x["s"] <= 1 and x["d"] is None for x in v0["items"])
    assert sum(t["n"] for t in v0["topics"]) == len(v0["items"]) == v0["summary"]["n_items"]
    assert {a["v"] for a in v0["anchored"]} == set(fake_client.get(f"/api/sessions/{sid}").json()["current_state"])
    # map positions for the landscape view (topic layout even without model dependencies)
    assert all(0 <= x["x"] <= 1 and 0 <= x["y"] <= 1 for x in v0["items"])
    assert set(v0["topic_xy"]) == {t["name"] for t in v0["topics"]} | {a["t"] for a in v0["anchored"]}
    # cached per state
    assert fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json() == v0

    r = fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Should abortion be legal?"}).json()
    v1 = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert v1["step"] == 1 and v1["since_step"] == 0
    assert set(v1["new_anchored"]) <= set(r["state_updates"]) and bool(v1["new_anchored"]) == bool(r["state_changed"])
    answered = set(r["selected_variables"]) & set(v1["new_anchored"])
    assert not answered & {x["v"] for x in v1["items"]}  # answered items leave the predicted ring
    moved = [x for x in v1["items"] if x["d"] is not None and x["d"] > v1["shift_eps"]]
    assert v1["summary"]["n_moved"] == len(moved)
    assert all(0 <= x["d"] <= 1 for x in v1["items"] if x["d"] is not None)
    assert len(v1["history"]) == 1 and v1["history"][0]["since_step"] == 0

    fake_client.post(f"/api/sessions/{sid}/reset")
    v2 = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert v2["since_step"] is None and v2["history"] == []


def test_landscape_without_ideology(fake_client):
    sid = _session(fake_client, ideology=False)
    v = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert v["enabled"] and v["has_lean"] is False and v["ideology"] is None and not v.get("pending")
    assert v["items"] and all(x["l"] is None for x in v["items"])
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Should abortion be legal?"})
    v1 = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert v1["since_step"] == 0 and v1["step"] == 1


def test_landscape_is_computed_in_background(fake_client):
    sid = _session(fake_client, resp_mode="max")
    first = fake_client.get(f"/api/sessions/{sid}/landscape").json()
    assert first["enabled"] and (first.get("pending") or first.get("items"))
    ready = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    assert ready["items"] and not ready.get("pending")
    fake_client.post(f"/api/sessions/{sid}/questions", json={"question": "Should abortion be legal?"})
    nxt = fake_client.get(f"/api/sessions/{sid}/landscape").json()
    if nxt.get("pending"):  # previous landscape served while the new one is computed
        assert nxt["step"] == 0
    assert fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()["step"] == 1


def test_next_questions_without_ideology(fake_client):
    sid = _session(fake_client, ideology=False)
    v = fake_client.get(f"/api/sessions/{sid}/landscape?wait=true").json()
    n = fake_client.get(f"/api/sessions/{sid}/next-questions").json()
    assert n["enabled"] and not n["pending"] and n["open"]
    o = n["open"]
    assert o["question"] and o["t"] not in ("Background", "Other")
    assert o["s"] == min(x["s"] for x in v["items"] if x["t"] not in ("Background", "Other"))
    if n["connected"]:
        assert n["connected"]["v"] != o["v"]
    r = fake_client.post(f"/api/sessions/{sid}/questions", json={"question": o["question"]})
    assert r.status_code == 200 and r.json()["targeted"] is False
