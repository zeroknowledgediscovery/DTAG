"""Wave-specific GSS poles: resolution rules, generated files, runtime guard."""
from __future__ import annotations

import csv

import pytest

import pipeline as core
from conftest import ROOT
from polar_vectors import CANONICAL, WAVE_DIR, is_canonical, load_corrections, resolve_poles, wave_file


def test_corrections_and_symmetric_pairs():
    left = {"grass": "legal", "colmil": "not allowed", "viruses": "definitely not true", "abany": "yes", "pray": "never"}
    right = {"grass": "not legal", "colmil": "not fired", "viruses": "definitely true", "abany": "no", "pray": "several times a day"}
    support = {
        "grass": ["should be legal", "should not be legal"],
        "colmil": ["not allowed", "yes, allowed to teach"],
        "viruses": ["true", "false"],
        "abany": ["yes", "no"],
        "pray": ["several times a day", "once a day"],  # 'never' absent -> whole item dropped
    }
    L, R, rep = resolve_poles(left, right, support, load_corrections())
    assert L == {"grass": "should be legal", "colmil": "not allowed", "viruses": "false", "abany": "yes"}
    assert R == {"grass": "should not be legal", "colmil": "yes, allowed to teach", "viruses": "true", "abany": "no"}
    by = {r["item"]: r for r in rep}
    assert by["abany"]["status"] == "kept" and by["grass"]["status"] == "corrected"
    assert by["pray"]["status"] == "dropped" and "'never' not in labels" in by["pray"]["reason"]
    assert "pray" not in L and "pray" not in R, "a half-resolved item is dropped from BOTH poles"


def test_split_ballot_items_and_missing_items():
    left, right = {"bible": "book of fables", "libhomo": "not remove"}, {"bible": "inspired word", "libhomo": "remove"}
    support = {"biblev": ["ancient book", "inspired word", "word of god"], "biblenv": ["ancient book", "inspired word"]}
    L, R, rep = resolve_poles(left, right, support, load_corrections())
    assert L == {"biblev": "ancient book", "biblenv": "ancient book"}
    assert R == {"biblev": "inspired word", "biblenv": "inspired word"}
    assert any(r["item"] == "libhomo" and r["reason"] == "item not in wave" for r in rep)


def test_generated_wave_files_are_complete():
    files = sorted(WAVE_DIR.glob("gss_*_polar_vectors.csv"))
    assert len(files) == 35
    for f in files:
        L, R = core.load_polar_vectors_csv(str(f))
        assert L and set(L) == set(R), f.name
        assert all(L[v] != R[v] for v in L), f.name
    rows = list(csv.DictReader(open(WAVE_DIR / "pole_resolution_report.csv", encoding="utf-8")))
    kept = [r for r in rows if r["status"] != "dropped"]
    assert kept and all(r["L_used"] and r["R_used"] for r in kept)
    unresolved = {(r["wave"], r["item"]) for r in rows if r["status"] == "dropped" and r["reason"] != "item not in wave"}
    assert unresolved == {("1990", "pray"), ("2018", "prayfreq")}


def test_wave_file_selection():
    assert wave_file("/x/models/gss/gss_2024").name == "gss_2024_polar_vectors.csv"
    assert wave_file("/x/models/gss/gss_2024/") is not None
    assert wave_file("/x/models/wvs/wvs7_pooled") is None
    assert wave_file("/x/models/gss/gss_1901") is None
    assert is_canonical(str(CANONICAL)) and not is_canonical(str(WAVE_DIR / "gss_2024_polar_vectors.csv"))


def test_runtime_never_writes_unrecognised_pole_answers(fake_engine, tmp_path):
    from dtag_session import build_polar_geometry
    bad = tmp_path / "poles.csv"
    bad.write_text("variable,R,L\nabany,no,yes\ngunlaw,oppose,favour\nnotavar,x,y\npolviews,conservative,liberal\n")
    lm = fake_engine.registry.load("gss/gss_2024")
    ctx = lm.context(ROOT / "maps" / "gss" / "gss_2024_map.csv")
    g = build_polar_geometry(ctx, str(bad))
    assert g.left_map == {"abany": "yes", "polviews": "liberal"} and g.right_map == {"abany": "no", "polviews": "conservative"}
    reasons = {d["variable"]: d["reason"] for d in g.dropped}
    assert "L answer 'favour' not in labels" in reasons["gunlaw"]
    assert reasons["notavar"] == "item not in model"
    assert g.summary()["dropped_items"] and not g.summary()["wave_specific"]


def test_canonical_path_switches_to_wave_file(fake_engine):
    from dtag_session import build_polar_geometry
    lm = fake_engine.registry.load("gss/gss_2024")
    ctx = lm.context(ROOT / "maps" / "gss" / "gss_2024_map.csv")
    g = build_polar_geometry(ctx, str(CANONICAL))
    assert g.path.endswith("gss_2024_polar_vectors.csv") and g.summary()["wave_specific"]
    s = fake_engine.create_session(profile="gss2024_cm")
    poles = s.ideology_summary()["poles"]
    assert poles["file"] == "gss_2024_polar_vectors.csv" and poles["wave_specific"]


@pytest.mark.native
def test_real_model_poles_all_valid(native_engine):
    from dtag_session import build_polar_geometry
    lm = native_engine.registry.load("gss/gss_2024")
    ctx = lm.context(ROOT / "maps" / "gss" / "gss_2024_map.csv")
    g = build_polar_geometry(ctx, str(CANONICAL))
    assert g.enabled and g.path.endswith("gss_2024_polar_vectors.csv")
    assert [d for d in g.dropped if d["reason"] != "item not in model"] == []
    for v in g.left_map:
        assert g.left_map[v] in ctx.possible[v] and g.right_map[v] in ctx.possible[v]
    assert len(g.left_map) == 28
