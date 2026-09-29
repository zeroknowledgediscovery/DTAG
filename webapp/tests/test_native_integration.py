"""Integration tests against a real native LSM model (default: GSS 2024).

These do not mock the native runtime. The language layer is the
deterministic mock, so no OPENAI_API_KEY is needed.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import NATIVE_KEY, ROOT

pytestmark = pytest.mark.native

GSS_ONLY = pytest.mark.skipif(not NATIVE_KEY.startswith("gss/"), reason="GSS-specific profile test")
Q_IMM = "Which statement about immigrants matches your view?"
Q_REL = "How often do you attend religious services?"
Q_GUN = "Do you favor or oppose gun permits?"


def _strip(result: dict) -> dict:
    r = dict(result)
    for k in ("timings", "record"):
        r.pop(k, None)
    return r


@GSS_ONLY
def test_model_loads_once_shared_by_sessions_with_independent_state(native_engine):
    """Session A and B on gss_2024: one native load, one runtime, separate state."""
    reg = native_engine.registry
    a = native_engine.create_session(profile="gss2024_cm")
    loads_after_a = [e for e in reg.load_events if e["key"] == "gss/gss_2024"]
    b = native_engine.create_session(profile="gss2024_wf")
    loads_after_b = [e for e in reg.load_events if e["key"] == "gss/gss_2024"]
    assert len(loads_after_a) == 1 and loads_after_b == loads_after_a
    assert a.loaded is b.loaded
    assert a.loaded.backend._runtime is b.loaded.backend._runtime
    assert b.init_info["timings"]["model_was_resident"] == 1.0

    assert dict(a.session.state) != dict(b.session.state)
    b_before = dict(b.session.state)
    ra = a.ask(Q_IMM)
    assert ra["anchors"] and ra["mapping"]["type"] == "direct"
    assert dict(b.session.state) == b_before


def test_native_runtime_persistent_and_fast(native_engine):
    lm = native_engine.registry.load(NATIVE_KEY)
    backend = lm.backend
    runtime = backend._runtime
    row = [""] * len(backend.feature_names)
    target = backend.feature_names[backend.usable_tree_ids[0]]

    def timed(fn, n):
        out = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            out.append(time.perf_counter() - t0)
        return statistics.median(out)

    t_pred = timed(lambda: lm.model.predict_distributions(row, target_names=[target]), 5)
    t_q = timed(lambda: lm.model.qdistance(row, row), 3)
    t_d = timed(lambda: lm.model.distances_to_state(row, row, row), 3)
    # generous bounds: the old stateless binding took ~5 s / ~10 s per call
    assert t_pred < 0.25, t_pred
    assert t_q < 2.0, t_q
    assert t_d < 3.0, t_d
    assert backend._runtime is runtime, "runtime must not be reconstructed"
    assert native_engine.registry.load(NATIVE_KEY) is lm


@GSS_ONLY
def test_question_timings_have_no_reload_overhead(native_engine):
    s = native_engine.create_session(profile="gss2024_cm")
    r = s.ask(Q_REL)
    assert r["timings"]["native_predict"] < 0.5
    assert r["timings"]["ideology"] < 3.0
    assert r["ideology"]["enabled"] and r["ideology"]["after"] is not None


@GSS_ONLY
def test_semantic_modes_and_no_match_on_native_model(native_engine):
    ans = native_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "answer_only"})
    before = dict(ans.session.state)
    r = ans.ask("[semantic] How do you feel about climate change?")
    assert r["mapping"]["type"] in ("semantic_answer_only", "semantic_answer_only_low_confidence")
    assert dict(ans.session.state) == before and r["anchors"]

    upd = native_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "update_state"})
    r = upd.ask("[semantic] How do you feel about climate change?")
    assert r["mapping"]["type"] == "semantic_update_state" and r["state_updates"]
    assert r["ideology"]["after"] != r["ideology"]["before"] or r["state_changed"]

    nm = native_engine.create_session(profile="gss2024_cm")
    before = dict(nm.session.state)
    r = nm.ask("[nomatch] What is your favourite colour?")
    assert r["mapping"]["type"] == "no_match" and dict(nm.session.state) == before


@GSS_ONLY
def test_state_persists_across_questions_and_reset(native_engine):
    s = native_engine.create_session(profile="gss2024_cm")
    r1 = s.ask(Q_IMM)
    r2 = s.ask(Q_REL)
    for k, v in {**r1["state_updates"], **r2["state_updates"]}.items():
        assert s.session.state[k] == v
    assert [p["step"] for p in s.ideology_summary()["trajectory"]] == [0, 1, 2]
    s.reset()
    assert dict(s.session.state) == s.session.initial_state()
    assert s.ask(Q_IMM)["anchors"] == r1["anchors"], "same state + same seed -> same native anchors"


@GSS_ONLY
def test_concurrent_sessions_share_model_safely(native_engine):
    questions = [Q_IMM, Q_REL, Q_GUN]
    ref = native_engine.create_session(profile="gss2024_cm")
    expected = [_strip(ref.ask(q)) for q in questions]

    sessions = [native_engine.create_session(profile="gss2024_cm") for _ in range(4)]
    got: dict = {}
    errors = []

    def run(i, s):
        try:
            got[i] = [_strip(s.ask(q)) for q in questions]
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=run, args=(i, s)) for i, s in enumerate(sessions)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for i in range(len(sessions)):
        assert got[i] == expected
    assert len([e for e in native_engine.registry.load_events if e["key"] == NATIVE_KEY]) == 1


@GSS_ONLY
def test_api_end_to_end_on_native_model(native_engine):
    from fastapi.testclient import TestClient
    from dtag_web.app import create_app

    client = TestClient(create_app(engine=native_engine, frontend_dist=Path("/nonexistent")))
    s = client.post("/api/sessions", json={"profile": "gss2024_cm"}).json()
    sid = s["session_id"]
    assert s["model"]["loaded"] and s["ideology"]["enabled"]
    r1 = client.post(f"/api/sessions/{sid}/questions", json={"question": "What are your thoughts about immigration?"}).json()
    r2 = client.post(f"/api/sessions/{sid}/questions", json={"question": Q_REL}).json()
    for r in (r1, r2):
        assert "answer" in r and "timings" in r and r["ideology"]["enabled"]
    traj = client.get(f"/api/sessions/{sid}").json()["ideology"]["trajectory"]
    assert len(traj) == 3
    ex = client.get(f"/api/sessions/{sid}/export?format=json").json()
    assert ex["model"]["sha256"] and ex["model"]["release"] == "v0.2.0"
    assert ex["dtag"]["native_runtime"] == "bundled_persistent"
    assert client.get(f"/api/sessions/{sid}/export?format=csv").text.count("\n") == 3
    assert client.post(f"/api/sessions/{sid}/reset").json()["question_count"] == 0


@GSS_ONLY
def test_cli_still_runs_through_shared_session(native_model_root, tmp_path):
    env = dict(os.environ, DTAG_MODEL_ROOT=str(native_model_root), DTAG_LLM_BACKEND="mock")
    cmd = [
        sys.executable, str(ROOT / "scripts" / "pipeline_localized.py"),
        "--map", str(ROOT / "maps" / "gss" / "gss_2024_map.csv"),
        "--qnet", str(native_model_root / "gss" / "gss_2024"),
        "--persona", "45 year old conservative man",
        "--country", "United States", "--year", "2024",
        "--polar_vectors", str(ROOT / "assets" / "polar_vectors" / "polar_vectors.csv"),
        "--assets_dir", str(tmp_path / "assets"), "--logs_dir", str(tmp_path / "logs"),
        "--question", Q_IMM, "--timing",
    ]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "RESPONDENT ANSWER" in p.stdout and "IDEOLOGY INDEX" in p.stdout
    meta = json.loads(next((tmp_path / "logs").glob("*.meta.json")).read_text())
    assert meta["records"][0]["direct_mapping"] and meta["ideology_enabled"]
    assert "native_predict" in meta["records"][0]["timings"]


def _installed(root: Path, key: str) -> bool:
    return (root / key / "source_maps").is_dir()


def test_country_conditioning_when_models_installed(native_engine, native_model_root):
    """Categorical (Afrobarometer), coordinates (WVS), categorical EB labels."""
    checked = 0
    if _installed(native_model_root, "afrobarometer/r5"):
        a = native_engine.preview_conditioning("afrobarometer/r5", "Nigeria", "Africa", None)
        b = native_engine.preview_conditioning("afrobarometer/r5", "Ghana", "Africa", None)
        assert a["meta"]["geography_conditioning_mode"] == "categorical_country"
        assert a["forced"]["COUNTRY_ALPHA"] == "Nigeria" and b["forced"]["COUNTRY_ALPHA"] == "Ghana"
        checked += 1
    if _installed(native_model_root, "wvs/wvs7_pooled"):
        w = native_engine.preview_conditioning("wvs/wvs7_pooled", "India", "Asia", 2017)
        assert set(w["forced"]) == {"A_YEAR", "O1_LONGITUDE", "O2_LATITUDE"} and w["forced"]["A_YEAR"] == "2017"
        checked += 1
    if _installed(native_model_root, "eurobarometer/ZA7575_v1-0-0"):
        e = native_engine.preview_conditioning("eurobarometer/ZA7575_v1-0-0", "France", "Europe", None)
        assert e["forced"] == {"country": "FR - France"}
        g = native_engine.preview_conditioning("eurobarometer/ZA7575_v1-0-0", "Germany", "Europe", None)
        assert "country" not in g["forced"], "ambiguous East/West Germany must stay contextual"
        checked += 1
    g = native_engine.preview_conditioning(NATIVE_KEY, "United States", "", None)
    if NATIVE_KEY.startswith("gss/"):
        assert g["forced"] == {}
    if not checked:
        pytest.skip("no Afrobarometer/WVS/Eurobarometer model installed")


def test_existing_native_country_test_script(native_model_root):
    if not _installed(native_model_root, "afrobarometer/r5"):
        pytest.skip("afrobarometer/r5 not installed")
    env = dict(os.environ, DTAG_MODEL_ROOT=str(native_model_root))
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_country_conditioning.py")],
                       env=env, capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    assert p.returncode == 0 and "PASS deterministic country conditioning" in p.stdout, p.stdout + p.stderr
