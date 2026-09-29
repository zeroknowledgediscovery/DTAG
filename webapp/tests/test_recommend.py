"""Model recommendation from who/where/when, suggestions, eviction."""
from __future__ import annotations

import pytest

from dtag_recommend import norm_country


def _keys(r):
    return [c["model_key"] for c in r["candidates"]]


def test_country_normalisation():
    assert norm_country("FR - France") == "france"
    assert norm_country("NL - The Netherlands") == "netherlands"
    assert norm_country("GB-UKM - United Kingdom") == "united kingdom"
    assert norm_country("CY - Cyprus (Republic)") == "cyprus"
    assert norm_country("DEUTSCHLAND") == "germany"
    assert norm_country("Côte d'Ivoire") == norm_country("Cote d’Ivoire")
    assert norm_country("USA") == "united states"


def test_us_state_in_description_selects_gss(fake_engine):
    r = fake_engine.recommend("45 year old farmer in rural Alabama, conservative")
    assert r["resolved"]["country"] == "United States" and r["resolved"]["sources"]["country"] == "description"
    assert r["default"] == "gss/gss_2024"
    gss = r["candidates"][0]
    assert gss["geo"]["mode"] == "national_survey" and gss["overrides"] == {"year": 2024}


def test_year_picks_wave_and_round(fake_engine):
    r = fake_engine.recommend("farmer", "Nigeria", 2012)
    assert r["default"] == "afrobarometer/r5"
    top = r["candidates"][0]
    assert top["geo"]["mode"] == "categorical" and top["geo"]["value"] == "Nigeria"
    assert top["time"]["mode"] == "exact"
    assert r["choice_required"] and "wvs/wvs7_pooled" in _keys(r)
    r = fake_engine.recommend("x", "United States", 2023)  # fake catalog: GSS 2018/2022/2024
    assert r["default"] == "gss/gss_2024" and r["candidates"][0]["time"]["mode"] == "nearest"


def test_country_only_wvs(fake_engine):
    r = fake_engine.recommend("teacher", "India", 2018)
    assert _keys(r) == ["wvs/wvs7_pooled"] and not r["choice_required"]
    assert r["candidates"][0]["overrides"] == {"year": 2018}
    assert r["candidates"][0]["geo"]["mode"] == "coordinates"


def test_eurobarometer_date_routing(fake_engine):
    if not fake_engine.eurobarometer.available():
        pytest.skip("no Eurobarometer registry")
    r = fake_engine.recommend("retired teacher", "France", None, "2019-05-15")
    assert r["default"] == "eurobarometer/ZA7575_v1-0-0"
    top = r["candidates"][0]
    assert top["overrides"] == {"date": "2019-05-15"} and top["geo"]["value"] == "FR - France"


def test_defaults_and_unknown(fake_engine):
    r = fake_engine.recommend("", "", 2020)
    assert r["resolved"]["sources"]["country"] == "default"
    assert r["candidates"][0]["family"] == "gss", "an assumed-US respondent defaults to GSS"
    r = fake_engine.recommend("x", "Atlantis")
    assert r["candidates"] == [] and r["default"] is None and r["messages"]


def test_description_year_detection_ignores_birth_year(fake_engine):
    d = fake_engine.recommender.detect("woman born in 1970 living in Ghana in 2014")
    assert d["country"] == "Ghana" and d["year"] == 2014
    d = fake_engine.recommender.detect("man born in 1970")
    assert d["year"] is None


def test_recommended_session_request_is_valid(fake_engine):
    r = fake_engine.recommend("45 year old conservative man in Texas")
    c = r["candidates"][0]
    s = fake_engine.create_session(model_key=c["model_key"], overrides={"persona": "45 year old conservative man in Texas", **c["overrides"]})
    assert s.spec.model_key == "gss/gss_2024"


def test_preset_switched_to_other_family(fake_engine):
    spec = fake_engine.build_spec("gss2024_cm", {"model_key": "afrobarometer/r5", "country": "Nigeria"})
    assert spec.family == "afrobarometer" and spec.polar_set is None and not spec.ideology
    assert spec.year is None and "require_polar_vectors" not in spec.run


def test_suggestions_map_directly(fake_engine):
    s = fake_engine.create_session(profile="gss2024_cm")
    sug = fake_engine.suggestions(s)
    assert sug and all(x["top_variables"] for x in sug)
    s.ask(sug[0]["question"])
    assert sug[0]["question"] not in [x["question"] for x in fake_engine.suggestions(s)]


def test_api_recommend_countries_suggestions(fake_client):
    r = fake_client.post("/api/recommend", json={"persona": "nurse in Ghana", "year": 2014}).json()
    assert r["default"] == "afrobarometer/r6"
    assert fake_client.post("/api/recommend", json={"persona": "x", "path": "/etc"}).status_code == 422
    countries = fake_client.get("/api/countries").json()
    names = {c["name"]: c["families"] for c in countries}
    assert "afrobarometer" in names["Ghana"] and "gss" in names["United States"]
    sid = fake_client.post("/api/sessions", json={"profile": "gss2024_cm"}).json()["session_id"]
    sug = fake_client.get(f"/api/sessions/{sid}/suggestions").json()
    assert isinstance(sug, list) and sug


def test_resident_model_cap_evicts_lru(fake_engine, fake_model_root):
    d = fake_model_root / "gss" / "gss_2022"
    (d / "source_maps").mkdir(parents=True)
    (d / "trees" / "binary").mkdir(parents=True)
    reg = fake_engine.registry
    reg.max_loaded = 1
    a = reg.load("gss/gss_2024")
    b = reg.load("gss/gss_2022")
    assert list(reg.loaded) == ["gss/gss_2022"] and reg.evict_events[-1]["key"] == "gss/gss_2024"
    assert a is not b and reg.status("gss/gss_2024").state == "installed"
