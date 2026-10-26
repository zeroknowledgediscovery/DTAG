"""Regression coverage for the wider, read-only 2024 GSS wording audit."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "human_study" / "scripts"))
from audit_standalone_candidates import (
    CONFIRMED_SOURCE_INCOMPLETE,
    inspect, load_rows, signals, static_pool,
)


def test_full_map_static_audit_catches_proven_old_false_negatives():
    rows = load_rows()
    result = {r["variable"]: r for r in inspect(rows)}
    assert len(result) == 813
    for name in ("obey", "popular", "thnkself", "workhard", "helpoth",
                 "polescap", "confinan", "confed", "letin1", "letin1a",
                 "pornlaw", "rateincumb24", "marblk"):
        r = result[name]
        assert r["priority"] == "contracted_or_anchored", name
        assert r["contracted"], name
        assert r["static_or_native_candidate"], name

    assert result["acpttg"]["contracted"]
    assert result["chngdocs"]["contracted"]
    assert result["colmslm"]["contracted"]
    assert result["natenviy"]["special_source_anchor"]


def test_expanded_signals_see_short_fragments_and_missing_response_instructions():
    assert "short_label" in signals("accepting people")
    assert "short_label" in signals("to obey")
    assert "dependent_stem" in signals("Was attempting to escape from custody?")
    assert "unseen_scale_or_alternatives" in signals(
        "Which of these statements comes closest to your views?"
    )
    assert "broken_ending" in signals(
        "Do you think the number of immigrants to America nowadays should be"
    )
    assert "source_markup" in signals(
        "Now describe {GROUP} [IF SOMETHING]?"
    )
    assert signals("Do you believe there is a life after death?") == []


def test_screening_only_has_no_side_effects_on_candidate_universe():
    rows = load_rows()
    before = static_pool(rows)
    result = list(inspect(rows))
    after = static_pool(rows)
    assert before == after
    assert sum(x["static_or_native_candidate"] for x in result) == len(before)
    assert all(x["variable"] in before for x in result if x["static_or_native_candidate"])
    assert len(CONFIRMED_SOURCE_INCOMPLETE) >= 20
