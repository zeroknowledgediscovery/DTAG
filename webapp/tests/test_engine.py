"""Engine behaviour with a deterministic fake native backend (fast tier)."""
from __future__ import annotations

import threading

import pytest
import yaml

from conftest import ROOT, fake_manifest
from dtag_engine import DTAGEngineError, POLAR_VECTOR_SETS, canonical_map_key, map_inventory


def test_profile_discovery_is_dynamic(fake_engine):
    cfg = yaml.safe_load((ROOT / "configs" / "dtag_config.yaml").read_text())
    names = {p["name"] for p in fake_engine.list_profiles() if p["source"] == "configured"}
    assert names == set(cfg["interactive_profiles"])
    gss = fake_engine.get_profile("gss2024_cm")
    assert gss.model_key == "gss/gss_2024" and gss.map_key == "gss/gss_2024_map.csv"
    assert gss.ideology and gss.polar_set == "gss_default"
    # same run settings as the CLI launcher (interactive.py)
    assert gss.run["resp_mode"] == "max" and gss.run["k"] == 50 and gss.run["seed"] == 1000
    wvs = fake_engine.get_profile("wvs7_india_2017")
    assert wvs.model_key == "wvs/wvs7_pooled" and not wvs.ideology


def test_catalog_combines_manifest_installed_and_config(fake_engine):
    keys = fake_engine.catalog_keys()
    assert "gss/gss_2024" in keys and "eurobarometer/ZA7575_v1-0-0" in keys
    assert "afrobarometer/r9" in keys  # configured model, not in the fake manifest
    rec = fake_engine.model_record("gss/gss_2024")
    assert rec["installed"] and not rec["loaded"] and rec["map_available"] and rec["ideology_available"]
    assert not fake_engine.model_record("wvs/wvs7_pooled")["ideology_available"]


def test_every_catalog_model_has_a_canonical_map():
    import fetch_models
    try:
        m = fetch_models.load_manifest(timeout=30)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"manifest unreachable: {e}")
    missing = [k for k in m["models"] if canonical_map_key(k) is None]
    assert missing == []
    assert len({canonical_map_key(k) for k in m["models"]}) == 252


def test_override_validation(fake_engine):
    with pytest.raises(DTAGEngineError, match="Unsupported override"):
        fake_engine.build_spec("gss2024_cm", {"command": "rm -rf /"})
    with pytest.raises(DTAGEngineError):
        fake_engine.build_spec("gss2024_cm", {"semantic_fallback": "sometimes"})
    with pytest.raises(DTAGEngineError):
        fake_engine.build_spec("gss2024_cm", {"k": 10_000})
    with pytest.raises(DTAGEngineError, match="Unknown semantic map"):
        fake_engine.build_spec("gss2024_cm", {"map_key": "../../../etc/passwd"})
    with pytest.raises(DTAGEngineError, match="Unknown DTAG model"):
        fake_engine.build_spec("gss2024_cm", {"model_key": "gss/gss_1066"})
    with pytest.raises(DTAGEngineError, match="belongs to"):
        fake_engine.build_spec("gss2024_cm", {"map_key": "wvs7_variable_question_map.csv"})
    s = fake_engine.build_spec("gss2024_cm", {"persona": "30 year old nurse", "resp_mode": "draw", "seed": 7})
    assert s.persona == "30 year old nurse" and s.run["resp_mode"] == "draw" and s.run["seed"] == 7


def test_gss_year_selects_wave_model(fake_engine):
    s = fake_engine.build_spec("gss2024_cm", {"year": 2022})
    assert s.model_key == "gss/gss_2022" and s.map_key == "gss/gss_2022_map.csv"
    assert s.temporal["mode"] == "wave_model_selection"
    with pytest.raises(DTAGEngineError, match="No native GSS wave"):
        fake_engine.build_spec("gss2024_cm", {"year": 2023})


def test_polar_vectors_never_reused_across_families(fake_engine):
    assert POLAR_VECTOR_SETS["gss_default"]["families"] == ["gss"]
    for prof in ("wvs7_india_2017", "afrobarometer_r5_ghana"):
        with pytest.raises(DTAGEngineError, match="registered for"):
            fake_engine.build_spec(prof, {"polar_set": "gss_default"})
        s = fake_engine.build_spec(prof, {"ideology": True})
        assert not s.ideology and s.polar_set is None
    eb = fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0")
    assert not eb.ideology


def test_eurobarometer_routing(fake_engine):
    if not fake_engine.eurobarometer.available():
        pytest.skip("no Eurobarometer date registry")
    s = fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"date": "2019-05-15", "country": "France"})
    assert s.za == "ZA7575" and s.model_key == "eurobarometer/ZA7575_v1-0-0"
    assert s.temporal["mode"] == "fieldwork_date_routing"
    assert s.temporal["fieldwork"]["fieldwork_start"] == "2019-05-09"
    assert any("resolves to Eurobarometer ZA7575" in w for w in s.warnings)
    with pytest.raises(DTAGEngineError, match="ambiguous"):
        fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"year": 2019})
    with pytest.raises(DTAGEngineError, match="No Eurobarometer fieldwork interval"):
        fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"date": "1950-01-01"})
    z = fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"za": "7576"})
    assert z.za == "ZA7576" and z.model_key == "eurobarometer/ZA7576_v1-0-0" and z.temporal["mode"] == "explicit_za"
    with pytest.raises(DTAGEngineError, match="no native DTAG model"):
        fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"za": "ZA9999"})


def test_eurobarometer_without_registry(fake_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("DTAG_EURODATES", str(tmp_path / "missing.csv"))
    monkeypatch.setattr(fake_engine.eurobarometer, "registry_path", lambda: None)
    with pytest.raises(DTAGEngineError, match="date routing is unavailable"):
        fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"date": "2019-05-15"})
    s = fake_engine.build_spec(model_key="eurobarometer/ZA7575_v1-0-0", overrides={"za": "ZA7575"})
    assert s.temporal["fieldwork"] is None and s.temporal["date_registry_available"] is False


def test_model_loaded_once_and_shared(fake_engine):
    a = fake_engine.create_session(profile="gss2024_cm")
    b = fake_engine.create_session(profile="gss2024_wf")
    assert a.loaded is b.loaded
    assert fake_engine._test_loads == [str(fake_engine.registry.loaded["gss/gss_2024"].path)]
    assert len(fake_engine.registry.load_events) == 1
    assert a.session.state is not b.session.state
    assert a.session.ctx is b.session.ctx  # shared read-only model/map context


def test_concurrent_loads_single_runtime(fake_engine):
    results = []
    threads = [threading.Thread(target=lambda: results.append(fake_engine.registry.load("gss/gss_2024"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(r) for r in results}) == 1 and len(fake_engine._test_loads) == 1


def test_session_isolation_state_and_reset(fake_engine):
    a = fake_engine.create_session(profile="gss2024_cm")
    b = fake_engine.create_session(profile="gss2024_cm")
    init_b = dict(b.session.state)
    r = a.ask("Which statement about immigrants matches your view?")
    assert r["mapping"]["type"] == "direct" and r["state_updates"]
    assert dict(b.session.state) == init_b, "session B must not see session A's updates"
    assert b.session.query_count == 0
    a.ask("What about the environment?")
    a.reset()
    assert dict(a.session.state) == a.session.initial_state() and a.session.query_count == 0
    assert a.session.results == [] and len(a.session.ideology_series) == 1


def test_semantic_fallback_modes(fake_engine):
    s_ans = fake_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "answer_only"})
    before = dict(s_ans.session.state)
    r = s_ans.ask("[semantic] How do you feel about climate change?")
    assert r["mapping"]["type"] == "semantic_answer_only"
    assert r["state_updates"] == {} and not r["state_changed"] and dict(s_ans.session.state) == before
    assert r["anchors"], "answer_only still grounds the answer in native anchors"

    s_upd = fake_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "update_state"})
    r = s_upd.ask("[semantic] How do you feel about climate change?")
    assert r["mapping"]["type"] == "semantic_update_state" and r["state_updates"]
    assert all(s_upd.session.state[k] == v for k, v in r["state_updates"].items())

    s_low = fake_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "answer_only"})
    before = dict(s_low.session.state)
    r = s_low.ask("[lowconf] How do you feel about climate change?")
    assert r["mapping"]["type"] == "semantic_answer_only_low_confidence" and dict(s_low.session.state) == before

    s_off = fake_engine.create_session(profile="gss2024_cm", overrides={"semantic_fallback": "off"})
    r = s_off.ask("[semantic] How do you feel about climate change?")
    assert r["mapping"]["type"] == "no_match"


def test_no_match_preserves_state_and_carries_ideology(fake_engine):
    s = fake_engine.create_session(profile="gss2024_cm")
    before = dict(s.session.state)
    r = s.ask("[nomatch] What is your favourite colour?")
    assert r["mapping"]["label"] == "NO MATCH" and not r["state_changed"]
    assert dict(s.session.state) == before
    assert r["ideology"]["enabled"] and r["ideology"]["before"] == r["ideology"]["after"]


def test_response_mode_applies_to_native_anchor(fake_engine):
    s = fake_engine.create_session(profile="gss2024_cm", overrides={"resp_mode": "max"})
    r = s.ask("Which statement about immigrants matches your view?")
    for a in r["anchors"]:
        assert a["response"] == max(a["distribution"], key=a["distribution"].get)
        assert abs(sum(a["distribution"].values()) - 1.0) < 1e-6


def test_geography_reporting_is_honest(fake_engine):
    s = fake_engine.create_session(profile="gss2024_cm")
    geo = s.geographic_conditioning
    assert geo["requested_country"] == "United States"
    assert geo["conditioning_mode"] == "survey_context_only" and geo["conditioned_variables"] == {}
    t = s.temporal_conditioning
    assert t["mode"] == "wave_model_selection" and t["conditioned_variables"] == {}


def test_custom_profiles_persist_outside_config(fake_engine):
    cfg_before = (ROOT / "configs" / "dtag_config.yaml").read_text()
    spec = fake_engine.build_spec("gss2024_cm", {"persona": "custom persona", "semantic_fallback": "off"})
    saved = fake_engine.save_profile("my_custom", spec)
    assert saved.source == "custom" and saved.persona == "custom persona" and saved.run["semantic_fallback"] == "off"
    assert "my_custom" in {p["name"] for p in fake_engine.list_profiles()}
    assert (ROOT / "configs" / "dtag_config.yaml").read_text() == cfg_before
    with pytest.raises(DTAGEngineError):
        fake_engine.save_profile("gss2024_cm", spec)
    with pytest.raises(DTAGEngineError):
        fake_engine.save_profile("../evil", spec)


def test_export_contains_reproducibility_metadata(fake_engine):
    s = fake_engine.create_session(profile="gss2024_cm", overrides={"resp_mode": "draw", "seed": 11})
    s.ask("Which statement about immigrants matches your view?")
    s.ask("[nomatch] colour?")
    ex = fake_engine.export_session(s)
    for key in ("dtag", "profile", "model", "map", "persona", "geography", "time", "config", "random_seed",
                "response_mode", "semantic_fallback", "llm", "initialization", "ideology", "questions",
                "records_cli_schema", "final_state"):
        assert key in ex, key
    assert ex["dtag"]["version"] and ex["model"]["key"] == "gss/gss_2024" and ex["model"]["release"] == "vTEST"
    assert ex["random_seed"] == 11 and ex["response_mode"] == "draw"
    assert ex["initialization"]["initial_state"] and len(ex["questions"]) == 2
    q = ex["questions"][0]
    assert q["anchors"][0]["distribution"] and q["selected_variables"] and "timings" in q
    assert [p["step"] for p in ex["ideology"]["trajectory"]] == [0, 1, 2]
    csv_text = fake_engine.export_csv(s)
    assert csv_text.count("\n") == 3 and "NO MATCH" in csv_text


def test_map_inventory_is_repository_only():
    inv = map_inventory()
    assert all(p.is_file() and str(p).startswith(str((ROOT / "maps").resolve())) for p in inv.values())
    assert sum(1 for k in inv if k.startswith("eurobarometer/")) == 207
    assert sum(1 for k in inv if k.startswith("gss/")) == 35


def test_manifest_unreachable_does_not_break_installed_models(fake_engine):
    fake_engine.manifest._manifest = None
    fake_engine.manifest.get = lambda refresh=False: None  # type: ignore[assignment]
    s = fake_engine.create_session(profile="gss2024_cm")
    assert s.session.state
    with pytest.raises(DTAGEngineError, match="manifest is unreachable"):
        fake_engine.registry.install("gss/gss_2022")
    assert fake_manifest()  # helper still importable
