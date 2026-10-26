"""Grounded human-study prompt: complete options, provenance and corrective retry.

Tests use a scriptable JSON response client; no external LLM/GCP network calls.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from human_study.grounded_generation import (
    make_prompt, response_requirements, validate_complete_choices,
    has_unresolved_choice_reference, craft_question,
)
from human_study.questions import QuestionLLM, QuestionGenerationError
from human_study.wording_contracts import (
    INCOME16_RANGES, context_for_native_item, context_for,
)


class Responses:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.prompts = []
        self.text_formats = []

    def create(self, *, model, input, text):
        self.prompts.append(input)
        self.text_formats.append(text)
        return SimpleNamespace(output_text=json.dumps(next(self.answers)))


def client(*answers):
    return SimpleNamespace(responses=Responses(*answers))


def generated(question, missing=False, details=""):
    return {"question": question, "missing_context": missing, "missing_details": details}


def item(name, description, opts):
    return SimpleNamespace(
        item_id=name,
        original_wording=description,
        source_text_incomplete=True,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x) for x in opts),
    )


def service_llm(api):
    llm = object.__new__(QuestionLLM)
    llm.backend = "openai"
    llm.client = api
    llm.config = SimpleNamespace(
        llm_model="scripted-test",
        prompt_version="dtag-human-grounded-test",
        question_mode="llm_required",
        candidate_mode="native_webapp",
    )
    return llm


def test_full_26_option_source_is_present_in_prompt_and_requirements():
    label = "In which of these groups did your earnings fall?"
    source = context_for("rincom16").source
    prompt = make_prompt("rincom16", label, source, INCOME16_RANGES,
                         original_codebook={"excerpt": "Variable: RINCOM16\nLabel: earnings before taxes",
                                            "pdf_pages": [118]})
    assert "ALL 26 MODEL-NATIVE RESPONSES, NO TRUNCATION" in prompt
    assert "one sentence" not in prompt
    assert "multiple sentences" in prompt
    assert "$170,000 or over" in prompt
    assert "Label: earnings before taxes" in prompt
    assert response_requirements(source, INCOME16_RANGES) == list(INCOME16_RANGES)
    assert len(validate_complete_choices("Which of the following ranges would you choose?",
                                         source, INCOME16_RANGES)) == 26
    assert validate_complete_choices(source, source, INCOME16_RANGES) == []


def test_real_json_generation_retries_with_missing_ranges_diagnostic(monkeypatch):
    import human_study.grounded_generation as evidence
    monkeypatch.setattr(evidence, "source_entry", lambda v: {
        "excerpt": "Variable: RINCOM16\nLabel: earnings before taxes",
        "pdf_pages": [118],
    })
    source = context_for("rincom16").source
    api = client(
        generated("Which of the following earnings ranges describes your income?"),
        generated(source),
    )
    record = service_llm(api).generate(item("rincom16", "Which of these groups did your earnings fall into?",
                                             INCOME16_RANGES))
    # Same wording as restored source triggers no-rewrite protection; reject
    # rather than falsely treating a provider echo as independent LLM output.
    assert record["question_provenance"]["fallback"] is True
    assert len(api.responses.prompts) == 2
    assert "VALIDATION FAILURES TO CORRECT ON THIS RETRY" in api.responses.prompts[1]
    assert "$170,000 or over" in api.responses.prompts[1]
    assert "omitted these native alternatives" in api.responses.prompts[1]
    assert record["question_provenance"]["attempts"][0]["rejected"] == "response_alternatives_not_displayed"


def test_no_source_premise_cannot_be_invented_when_llm_reports_missing():
    api = client(
        generated("", True, "original target population is missing"),
        generated("", True, "original target population is missing"),
    )
    with pytest.raises(QuestionGenerationError) as exc:
        service_llm(api).generate(item(
            "unknown_incomplete_question", "accepting people",
            ["too far", "about far enough", "not far enough"],
        ))
    assert all(a["rejected"] == "original_context_unavailable"
               for a in exc.value.attempts)
    assert "original target population is missing" in api.responses.prompts[1]
    assert "No verified item-specific wording contract exists" in api.responses.prompts[0]


def test_race_third_identity_preserves_applicability_and_native_list():
    actual = ["White", "Black", "Other Pacific Islander"]
    source = context_for_native_item("racecen3", actual).source
    valid = ("If you identify with at least three racial identities, "
             "which additional race would you name third? "
             "Options are White; Black; Other Pacific Islander. "
             "If you identify with fewer than three, please answer not applicable?")
    api = client(
        generated("Which third race are you: White, Black, or Other Pacific Islander?"),
        generated(valid),
    )
    record = service_llm(api).generate(item("racecen3", "Third mention of race", actual))
    assert record["displayed_wording"] == valid
    assert record["question_provenance"]["validation_method"] == (
        "gss_2024_grounded_source_and_contract_v2"
    )
    assert record["question_provenance"]["attempts"][0]["rejected"] == (
        "required_referent_or_scale_missing"
    )
    assert "at least three" in api.responses.prompts[1]


def test_anchored_vignette_can_use_such_a_person_after_antecedent():
    text = ("Imagine a Muslim clergyman who preaches hatred of the United States. "
            "Do you think such a person should be allowed to teach in a college or university?")
    assert not has_unresolved_choice_reference(text, text, ["allow", "do not allow"])
    assert has_unresolved_choice_reference(
        "Do you think such a person should be allowed to teach?",
        "Do you think such a person should be allowed to teach?",
        ["allow", "do not allow"],
    )


def test_unknown_options_and_self_certification_not_enough():
    q = ("Which of the following statements do you prefer: "
         "make no changes, make some changes, or make large changes?")
    choices = ["make no changes", "make some changes", "make large changes"]
    assert not validate_complete_choices(q, q, choices)
    assert not has_unresolved_choice_reference(q, q, choices)
    assert validate_complete_choices(
        "Which of the following statements do you prefer?",
        q, choices,
    ) == choices
    numeric = [str(i) for i in range(101)]
    # The numeric feeling thermometer does not need 101 copied integers.
    assert response_requirements("Rate your feeling on a scale of 0 to 100?", numeric) == []


def test_builder_rejects_static_228_candidate_subset():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "human_study" / "scripts"))
    from build_gss2024_source_catalog import build
    with pytest.raises(ValueError, match="811-variable"):
        build({"summary": {
            "model_key": "gss/gss_2024",
            "total_native_model_variables": 228,
            "all_native_variables_enumerated": True,
            "semantic_map_matched": 228,
        }, "variables": []})
