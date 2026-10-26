"""Regression tests: generated GSS questions must retain essential referents."""
from types import SimpleNamespace

import pytest

from human_study.wording_contracts import CONTRACTS, context_for, validates_wording, validates_standalone
from human_study.questions import QuestionGenerationError, QuestionLLM


def test_all_context_sources_are_self_contained():
    for variable, contract in CONTRACTS.items():
        assert validates_wording(variable, contract.source), variable


@pytest.mark.parametrize("variable", ["workwhts", "workblks", "workhsps",
                                      "wlthwhts", "wlthblks", "wlthhsps"])
def test_group_rating_requires_group_and_correct_scale(variable):
    source = context_for(variable).source
    assert validates_wording(variable, source)
    # An apparently grammatical survey question without the named group is not valid.
    group = {
        "whts": "White people", "blks": "Black people",
        "hsps": "Hispanic Americans",
    }[variable[-4:]]
    assert not validates_wording(variable, source.replace(group, "this group"))
    # Reversed scale anchors change the meaning of the response codes.
    if variable.startswith("work"):
        reversed_source = source.replace("hard-working", "TEMP").replace(
            "lazy", "hard-working").replace("TEMP", "lazy")
    else:
        reversed_source = source.replace("rich", "TEMP").replace(
            "poor", "rich").replace("TEMP", "poor")
    assert not validates_wording(variable, reversed_source)


def test_history_measures_pride_in_america_not_personal_history():
    assert validates_wording("proudhis", "How proud are you of America's history?")
    assert not validates_wording("proudhis", "How proud are you of its history?")
    assert not validates_wording("proudhis", "How proud are you of your personal history?")


def fake_item(variable):
    return SimpleNamespace(
        item_id=variable, original_wording="how proud its history" if variable == "proudhis"
        else "Now I have some questions about different groups in our society.",
        source_text_incomplete=True,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x)
                      for x in (("very proud", "somewhat proud")
                                if variable == "proudhis" else ("hard-working", "lazy"))),
    )


def fake_llm():
    llm = object.__new__(QuestionLLM)
    llm.client = object()
    llm.backend = "openai"
    llm.config = SimpleNamespace(
        llm_model="scripted-test", prompt_version="wording-contract-test",
        question_mode="llm_required", candidate_mode="native_webapp",
    )
    return llm


def test_generate_retries_missing_group_and_preserves_original_map_source(monkeypatch):
    import dtag_core

    attempts = iter([
        "Using a scale from 1 to 7, where 1 means almost all people in the group "
        "are hard-working and 7 means almost all are lazy, how would you rate "
        "the people in this group?",
        "On a scale from 1 to 7 where 1 is hard-working and 7 is lazy, "
        "how would you rate Hispanic Americans?",
    ])
    inputs = []

    def generate(_client, source, _choices, _model, **kwargs):
        inputs.append(source)
        assert kwargs == {"source_incomplete": True}
        return next(attempts)

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", generate)
    record = fake_llm().generate(fake_item("workhsps"))
    assert len(inputs) == 2
    assert "Hispanic Americans" in inputs[0]
    assert record["displayed_wording"].endswith("Hispanic Americans?")
    assert record["question_provenance"]["validation_method"] == (
        "gss_2024_referent_scale_contract_v1"
    )
    assert record["question_provenance"]["attempts"][0]["rejected"] == (
        "required_referent_or_scale_missing"
    )


def test_generate_fails_closed_when_history_referent_lost(monkeypatch):
    import dtag_core

    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs: "How proud are you of its history?",
    )
    with pytest.raises(QuestionGenerationError) as exc:
        fake_llm().generate(fake_item("proudhis"))
    assert len(exc.value.attempts) == 2
    assert all(a["rejected"] == "required_referent_or_scale_missing"
               for a in exc.value.attempts)



def test_colmslm_requires_the_specific_referent_and_action():
    contract = context_for("colmslm")
    assert contract is not None
    assert "Muslim clergyman" in contract.source
    assert "hatred of the United States" in contract.source
    assert "college or university" in contract.source
    assert validates_wording("colmslm", contract.source)
    for flawed in [
        "Do you think this person should be allowed to teach in a college or university?",
        "Should such a person be allowed to teach in a college or university?",
        "Should a Muslim clergyman be allowed to teach in a college?",
        "Should a person who hates the United States be allowed to teach in college?",
        "Should a Muslim clergyman who preaches hatred of the US be allowed to give a speech?",
    ]:
        assert not validates_wording("colmslm", flawed), flawed


@pytest.mark.parametrize("variable,required", [
    ("colath", "churches"), ("libath", "religion"),
    ("colrac", "Black people"), ("librac", "genetically inferior"),
    ("colcom", "Communist"), ("libcomy", "Communist"),
    ("libmslm", "Muslim clergyman"), ("libmslmy", "Islamic religious leader"),
    ("abnomore", "abortion"), ("abrape", "abortion"),
    ("abanyg", "abortion"), ("suicide2g", "right"),
    ("eqwlth", "income"), ("natfare", "welfare"),
    ("natfarey", "assistance to the poor"),
    ("conjudge", "Supreme Court"), ("polabuse", "police officer"),
])
def test_contextual_survey_families_have_named_referents(variable, required):
    contract = context_for(variable)
    assert contract is not None, variable
    assert required.casefold() in contract.source.casefold()
    assert validates_wording(variable, contract.source), variable


def test_generic_standalone_rejects_orphan_subjects_and_codebook_markup():
    bad = [
        "Do you think this person should be allowed to teach in a university?",
        "Should such a person be allowed to teach?",
        "Should he be fired?",
        "If she becomes pregnant as a result of rape?",
        "Would you favor removing this book?",
        "What do you think about {#secl_name}?",
        "Do you think this is acceptable ...?",
    ]
    assert all(not validates_standalone(q) for q in bad)
    good = [
        "Consider a Muslim clergyman who preaches hatred of the United States. "
        "Do you think such a person should be allowed to teach in a university?",
        "Would you allow a person who has opposed religion to speak in your community?",
    ]
    assert all(validates_standalone(q) for q in good)


def test_colmslm_generator_retries_and_fails_closed_for_missing_person(monkeypatch):
    import dtag_core

    source_inputs = []
    def generate(_client, source, _choices, _model, **kwargs):
        source_inputs.append(source)
        return "Do you think this person should be allowed to teach in a college or university?"

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", generate)
    item = SimpleNamespace(
        item_id="colmslm",
        original_wording="Should such a person be allowed to teach in a college or university, or not?",
        source_text_incomplete=False,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x)
                      for x in ("yes, allowed to teach", "not allowed")),
    )
    with pytest.raises(QuestionGenerationError) as exc:
        fake_llm().generate(item)
    assert len(source_inputs) == 2
    assert all("Muslim clergyman" in prompt for prompt in source_inputs)
    assert all(a["rejected"] == "incomplete_standalone_question"
               for a in exc.value.attempts)


def test_colmslm_generator_accepts_complete_referent(monkeypatch):
    import dtag_core

    complete = (
        "Imagine a Muslim clergyman who preaches hatred of the United States. "
        "Do you think such a person should be allowed to teach in a college or university?"
    )
    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs: complete,
    )
    item = SimpleNamespace(
        item_id="colmslm",
        original_wording="Should such a person be allowed to teach in a college or university, or not?",
        source_text_incomplete=False,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x)
                      for x in ("yes, allowed to teach", "not allowed")),
    )
    record = fake_llm().generate(item)
    assert record["displayed_wording"] == complete
    assert record["question_provenance"]["source_reference"].endswith("GSS%202024%20Codebook%20R2.pdf")
