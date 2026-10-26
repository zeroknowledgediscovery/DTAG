"""Offline coverage tests for the exhaustive native GSS source inventory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "human_study" / "scripts"))

from audit_all_native_gss_2024 import (
    audit_all, summarize, parse_codebook_text_pages,
    RANGE_QUESTION, RELEASE_FEATURE_COUNT,
)


def test_full_native_audit_never_filters_demographics_opinions_or_batteries():
    names = [
        ("rincom16", ["Under $1,000", "$1,000 to $2,999"]),
        ("racecen3", ["White", "Black", "Not applicable"]),
        ("obey", ["first", "second", "third", "fourth", "fifth"]),
        ("natfare", ["too much", "about right", "too little"]),
        ("hrs1", ["0", "1", "2"]),
        ("random_native_column", []),
    ]
    semantic = {
        "rincom16": {"question_text_filled": "Which of these groups did your earnings fall into?"},
        "racecen3": {"question_text_filled": "Third mention of race"},
        "obey": {"question_text_filled": "to obey"},
        "natfare": {"question_text_filled": "Government spending on welfare?"},
        "hrs1": {"question_text_filled": "IF WORKING: How many hours last week?"},
    }
    rows = audit_all(names, semantic)
    assert [r["variable"] for r in rows] == [p[0] for p in names]
    assert rows[0]["native_supported_answers"] == names[0][1]
    assert "source_references_external_choices" in rows[0]["flags"]
    assert "native_support_contains_reserved_or_not_applicable_values" in rows[1]["flags"]
    assert "model_variable_missing_semantic_map" in rows[-1]["flags"]
    assert rows[-1]["source_certification"] == "pending_independent_review"
    assert "eligibility_or_respondent_fact_requires_review" in rows[4]["flags"]
    assert all(r["source_certification"] != "verified" for r in rows)
    assert summarize(rows)["total_native_model_variables"] == len(names)


def test_codebook_entries_are_collected_across_repeated_pages():
    p = parse_codebook_text_pages([
        (165, "GSS R2\nVariable: RINCOM16 Type: Numeric\nLabel: Which income group?\n"
               "UNDER $1,000 1 30 0.9%\n"),
        (166, "GSS R2\nVariable: RINCOM16 Type: Numeric\n"
              "$170,000 OR OVER 26 128 3.9%\n"
              "Variable: REGION Type: Numeric\nLabel: Region\n"),
    ])
    assert p["rincom16"]["pages"] == [165, 166]
    assert len(p["rincom16"]["blocks"]) == 2
    assert p["region"]["pages"] == [166]


def test_income_ranges_and_2024_race_context_are_reviewed():
    from human_study.wording_contracts import (
        INCOME16_RANGES, context_for_native_item, validates_wording,
    )
    assert len(INCOME16_RANGES) == 26
    assert RANGE_QUESTION.search("In which of the following ranges?")
    income = context_for_native_item("rincom16", INCOME16_RANGES)
    assert income is not None
    assert all(r in income.source for r in INCOME16_RANGES)
    race = context_for_native_item(
        "racecen3", ("White", "Black", "Other Pacific Islander")
    )
    assert "not applicable" in race.source
    assert "at least three" in race.source
    assert "Other Pacific Islander" in race.source
    assert "Guamanian or Chamorro" not in race.source
    assert validates_wording("racecen3", race.source, contract_override=race)


def test_release_definition_is_all_811_not_empty_state_228():
    assert RELEASE_FEATURE_COUNT == 811
