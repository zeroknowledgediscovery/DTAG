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


def test_generate_recovers_complete_source_when_history_referent_lost(monkeypatch):
    import dtag_core

    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs: "How proud are you of its history?",
    )
    record = fake_llm().generate(fake_item("proudhis"))
    assert record["displayed_wording"] == "How proud are you of America's history?"
    provenance = record["question_provenance"]
    assert provenance["provider"] == "source-validated"
    assert provenance["fallback"] is True
    assert provenance["source_standalone_verified"]
    assert provenance["validation_method"] == "source_grounded_standalone_fallback_v1"
    assert len(provenance["attempts"]) == 2
    assert all(a["rejected"] == "required_referent_or_scale_missing"
               for a in provenance["attempts"])

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


def test_colmslm_generator_recovers_full_person_context_after_bad_rewrites(monkeypatch):
    import dtag_core

    source_inputs = []
    def generate(_client, source, _choices, _model, **kwargs):
        source_inputs.append(source)
        return "Do you think this person should be allowed to teach in a college or university?"

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", generate)
    item = SimpleNamespace(
        item_id="colmslm",
        original_wording="Should such a person be allowed to teach in a college or university, or not?",
        source_text_incomplete=True,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x)
                      for x in ("yes, allowed to teach", "not allowed")),
    )
    result = fake_llm().generate(item)
    assert len(source_inputs) == 2
    assert all("Muslim clergyman" in prompt for prompt in source_inputs)
    assert "Muslim clergyman" in result["displayed_wording"]
    assert "hatred of the United States" in result["displayed_wording"]
    assert "college or university" in result["displayed_wording"]
    assert result["question_provenance"]["fallback"]
    assert result["question_provenance"]["source_standalone_verified"]
    assert all(a["rejected"] == "incomplete_standalone_question"
               for a in result["question_provenance"]["attempts"])

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



@pytest.mark.parametrize("number,cause", [
    (1, "racial discrimination"),
    (2, "inborn difference in ability"),
    (3, "unequal opportunities for education"),
    (4, "motivation or willpower"),
    (5, "upbringing"),
])
def test_all_five_racdif_historical_variants_are_standalone(number, cause):
    original = context_for(f"racdif{number}")
    variant = context_for(f"racdif{number}x")
    assert original is not None and variant is not None
    assert cause in variant.source
    assert "50 years" in variant.source
    assert "historical comparison" in variant.source
    assert variant.source.endswith(original.source)
    assert validates_standalone(variant.source)
    assert validates_wording(f"racdif{number}x", variant.source)
    assert "GSS2024_Ballot1_English.pdf" in variant.source_reference
    # Without the historical comparison intro the experimental form is lost.
    assert not validates_wording(f"racdif{number}x", original.source)
    # A historical intro with an unspecified cause is equally incomplete.
    truncated = (
        "The GSS has studied racial inequality for almost 50 years. "
        "For historical comparison, do you think Black people have worse "
        "jobs than White people because most?"
    )
    assert not validates_wording(f"racdif{number}x", truncated)


def test_racdif_x_uses_complete_source_for_generation(monkeypatch):
    import dtag_core

    generated = (
        "Research has asked similar questions for almost 50 years. "
        "For historical comparison, do you think that racial discrimination "
        "mainly explains differences in jobs and income between Black "
        "people and White people?"
    )
    source_inputs = []

    def generate(_client, source, _choices, _model, **kwargs):
        source_inputs.append(source)
        assert kwargs == {"source_incomplete": True}
        if len(source_inputs) == 1:
            return (
                "Do you think differences in jobs and income between Black "
                "people and White people are due to discrimination?"
            )
        return generated

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", generate)
    item = fake_item("racdif1x")
    record = fake_llm().generate(item)
    assert record["displayed_wording"] == generated
    assert len(source_inputs) == 2
    assert all("racial discrimination" in x for x in source_inputs)
    assert record["question_provenance"]["attempts"][0]["rejected"] == (
        "required_referent_or_scale_missing"
    )
    assert record["question_provenance"]["validation_method"] == (
        "gss_2024_referent_scale_contract_v1"
    )
    assert "GSS2024_Ballot1_English.pdf" in record["question_provenance"]["source_reference"]


def test_full_prolific_configs_retain_all_five_variants():
    from pathlib import Path
    from human_study.study_config import StudyConfig

    root = Path(__file__).resolve().parents[2]
    for suffix in ("study.prolific.example.yaml", "study.prolific.gcptest.yaml"):
        config = StudyConfig.load(root / "human_study/config" / suffix)
        for i in range(1, 6):
            assert f"racdif{i}x" not in config.excluded_ids
        assert config.excluded_ids == ()
        assert config.candidate_mode == "native_webapp"



def test_restored_variants_pass_unmodified_webapp_askable_filter():
    """Ensure the original optimizer still regards the 5 variants as candidates."""
    import csv
    from pathlib import Path

    from optimize_question_sets import askable

    root = Path(__file__).resolve().parents[2]
    with (root / "maps/gss/gss_2024_map.csv").open(newline="", encoding="utf-8") as fp:
        rows = {r["variable"]: r for r in csv.DictReader(fp)}
    for i in range(1, 6):
        name = f"racdif{i}x"
        row = rows[name]
        label = row["question_text_filled"] or row["question_text"]
        assert askable(name, label, set()), (
            f"Native webapp would suppress reconstructed item: {name}"
        )



def test_native_complete_map_question_can_recover_from_llm_outage(monkeypatch):
    import dtag_core

    def fail(*args, **kwargs):
        raise RuntimeError("simulated OpenAI upstream failure")

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", fail)
    item = SimpleNamespace(
        item_id="synthetic_uncontracted_survey_item",
        original_wording="Do you think people should be allowed to discuss these political ideas in public?",
        source_text_incomplete=True,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x) for x in ("yes", "no")),
    )
    result = fake_llm().generate(item)
    assert result["displayed_wording"] == item.original_wording
    assert result["question_provenance"]["provider"] == "source-validated"
    assert result["question_provenance"]["validation_method"] == (
        "native_map_validated_standalone_fallback_v1"
    )
    assert [a["error"] for a in result["question_provenance"]["attempts"]] == [
        "RuntimeError", "RuntimeError"
    ]


@pytest.mark.parametrize("fragment", [
    "Should such a person be allowed to teach in a college or university?",
    "Do you think this person should be allowed to teach in a college or university?",
    "(In general...) Do you agree with this?",
    "Improving and protecting the environment",
    "If she does not want to have another child?",
])
def test_unverified_fragments_still_fail_closed(monkeypatch, fragment):
    import dtag_core

    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs: "Do you think this person should be allowed to teach?",
    )
    item = SimpleNamespace(
        item_id="uncontracted_fragment",
        original_wording=fragment,
        source_text_incomplete=True,
        choices=tuple(SimpleNamespace(native_value=x, display_label=x) for x in ("yes", "no")),
    )
    with pytest.raises(QuestionGenerationError):
        fake_llm().generate(item)


def test_all_source_contracts_admit_resilient_fallback_without_llm():
    """Catch bad canonical strings before an active participant discovers one."""
    llm = fake_llm()
    for variable, contract in CONTRACTS.items():
        item = SimpleNamespace(
            item_id=variable,
            original_wording="unreliable abbreviated semantic-map label",
            source_text_incomplete=True,
            choices=(SimpleNamespace(native_value="yes", display_label="yes"),),
        )
        candidate = llm._complete_source_fallback(item, contract, False, contract.source, [
            {"rejected": "required_referent_or_scale_missing"},
            {"error": "RuntimeError"},
        ])
        assert candidate is not None, variable
        assert candidate["question_provenance"]["source_standalone_verified"], variable
        assert validates_wording(variable, candidate["displayed_wording"]), variable
        assert validates_standalone(candidate["displayed_wording"]), variable



def test_multi_sentence_valid_norc_stem_recovers_when_llm_fails():
    llm = fake_llm()
    source = (
        "Some people think the government should support equal opportunities. "
        "Others think it should play a smaller role. "
        "Which of these two views comes closer to your opinion?"
    )
    item = SimpleNamespace(
        item_id="noncontracted_scenario",
        original_wording=source,
        source_text_incomplete=True,
        choices=(SimpleNamespace(native_value="one", display_label="one"),),
    )
    result = llm._complete_source_fallback(
        item, None, False, source, [{"error": "RuntimeError"}]
    )
    assert result is not None
    assert result["displayed_wording"] == source
    assert result["question_provenance"]["validation_method"] == (
        "native_map_validated_standalone_fallback_v1"
    )



def test_only_actual_duplicates_not_distinct_gss_constructs_are_suppressed():
    from human_study.question_identity import already_covered_ids, question_family

    asked = ("discaffw", "racdif5x", "amcit", "racerank1",
             "spkrac", "racopen", "cctv")
    candidates = [
        "discaffw", "discaffm", "fehire",
        "racdif1", "racdif5", "amcitizn", "uscitzn",
        "racerank2", "racecen3", "spkracy", "racopenv", "cctv",
    ]
    blocked = already_covered_ids(candidates, asked)
    assert blocked == {"discaffw", "spkracy", "racopenv", "cctv"}
    for distinct in ("racdif1", "racdif5", "discaffm", "fehire",
                     "amcitizn", "uscitzn", "racerank2", "racecen3"):
        assert distinct not in blocked
    assert question_family("racdif5x") != question_family("racdif1")
    assert question_family("discaffw") != question_family("fehire")
    assert question_family("racerank1") != question_family("racerank2")
    assert question_family("racopen") == question_family("racopenv")


@pytest.mark.parametrize("variable", [
    "racerank1", "racerank2", "racerank3",
    "racecen1", "racecen2", "racecen3",
    "racopen", "racopenv", "racopennv",
    "affrmact", "fejobaff", "fehire", "discaffw",
    "discaffwv", "discaffwnv", "discaffm", "discaff",
    "amcit", "amcitizn", "citizen", "uscitzn",
    "cctv", "polattak", "polattaky",
])
def test_repaired_race_hiring_citizenship_surveillance_sources_are_complete(variable):
    contract = context_for(variable)
    assert contract, variable
    assert validates_standalone(contract.source), variable
    assert validates_wording(variable, contract.source), variable
    assert "{" not in contract.source and "…" not in contract.source


def test_race_question_rejects_missing_options_and_uses_full_source(monkeypatch):
    import dtag_core

    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs:
        "Which of these racial identities do you identify with second most strongly?",
    )
    item = SimpleNamespace(
        item_id="racerank2",
        original_wording="After {RACERANK1}, which of these races do you identify most with?",
        source_text_incomplete=True,
        choices=(SimpleNamespace(native_value="White", display_label="White"),
                 SimpleNamespace(native_value="Black", display_label="Black")),
    )
    rendered = fake_llm().generate(item)
    text = rendered["displayed_wording"]
    assert rendered["question_provenance"]["fallback"] is True
    assert "second" in text and "White" in text
    assert "Black" in text
    assert "not applicable" in text
    # The 2024 recoded model may not contain every historical 16-option
    # race category: do not invent categories missing from native support.
    assert "Guamanian or Chamorro" not in text
    assert "{" not in text


def test_surveillance_source_names_actor_action_location_and_right():
    source = context_for("cctv").source
    for term in ("government", "video surveillance", "public areas",
                 "definitely should", "probably should", "should not"):
        assert term in source.lower()
    assert not validates_wording("cctv", "Should video surveillance be allowed?")



def test_acpttg_is_source_complete_and_preserves_three_position_scale():
    source = context_for("acpttg").source
    assert "American society" in source
    assert "accepting people whose sex differs" in source
    assert "assigned at birth" in source
    assert validates_standalone(source)
    assert validates_wording("acpttg", source)
    assert "GSS2024_Ballot1_English.pdf" in context_for("acpttg").source_reference

    # The actual participant-reported question, and similar grammatical
    # questions, MUST fail validation when the target population is absent.
    for incomplete in (
        "Do you think accepting people is done too far, not far enough, or about far enough?",
        "Do you think American society has gone too far, about far enough, "
        "or not far enough in accepting people?",
        "Has American society gone too far in accepting those people?",
        "Do you think American society has gone too far or not far enough "
        "in accepting transgender people?",
    ):
        assert not validates_wording("acpttg", incomplete), incomplete

    # An equivalently complete rewording can still pass.
    assert validates_wording(
        "acpttg",
        "Has American society gone too far, about far enough, or not far enough "
        "in accepting transgender people?",
    )


def test_acpttg_repairs_reported_item_28_after_bad_llm_rewrites(monkeypatch):
    import dtag_core

    inputs = []
    reported = (
        "Do you think accepting people is done too far, "
        "not far enough, or about far enough?"
    )

    def flawed_rewrite(_client, source, _choices, _model, **kwargs):
        inputs.append(source)
        return reported

    monkeypatch.setattr(dtag_core, "llm_craft_survey_question", flawed_rewrite)
    item = SimpleNamespace(
        item_id="acpttg",
        original_wording="accepting people",
        source_text_incomplete=True,
        choices=tuple(
            SimpleNamespace(native_value=v, display_label=v)
            for v in ("too far", "about far enough", "not far enough")
        ),
    )
    record = fake_llm().generate(item)
    assert len(inputs) == 2
    assert inputs == [context_for("acpttg").source] * 2
    assert record["displayed_wording"] == context_for("acpttg").source
    assert record["displayed_wording"] != reported
    assert record["question_provenance"]["provider"] == "source-validated"
    assert record["question_provenance"]["source_standalone_verified"] is True
    assert record["question_provenance"]["source_reference"].endswith(
        "GSS2024_Ballot1_English.pdf"
    )
    assert all(
        x["rejected"] == "required_referent_or_scale_missing"
        for x in record["question_provenance"]["attempts"]
    )


def test_chngdocs_document_rights_requires_birth_context():
    source = context_for("chngdocs").source
    assert validates_standalone(source)
    assert validates_wording("chngdocs", source)
    assert "driver's license" in source
    assert "assigned at birth" in source
    assert "GSS2024_Ballot1_English.pdf" in context_for("chngdocs").source_reference
    assert not validates_wording(
        "chngdocs", "Should the law allow changing official documents?"
    )
    assert not validates_wording(
        "chngdocs",
        "Should the law allow people to change the sex listed on official "
        "documents like a driver's license?",
    )



def test_live_item23_earnings_ranges_cannot_be_omitted(monkeypatch):
    import dtag_core
    from human_study.wording_contracts import INCOME16_RANGES

    incomplete = ("In which of the following earnings ranges did your "
                  "income fall last year?")
    monkeypatch.setattr(
        dtag_core, "llm_craft_survey_question",
        lambda *_args, **_kwargs: incomplete,
    )
    item = SimpleNamespace(
        item_id="rincom16", original_wording="Which of these groups did your earnings fall into?",
        source_text_incomplete=True,
        choices=tuple(
            SimpleNamespace(native_value=r, display_label=r)
            for r in INCOME16_RANGES
        ),
    )
    record = fake_llm().generate(item)
    assert record["question_provenance"]["provider"] == "source-validated"
    assert record["question_provenance"]["fallback"] is True
    for label in INCOME16_RANGES:
        assert label in record["displayed_wording"]
    assert len(INCOME16_RANGES) == 26
    assert not validates_wording("rincom16", incomplete)


@pytest.mark.parametrize("variable", ["racecen2", "racecen3", "racerank2", "racerank3"])
def test_ranked_race_mentions_are_conditional_and_not_applicable(variable):
    from human_study.wording_contracts import context_for_native_item
    source = context_for(variable).source
    assert "not applicable" in source
    assert "at least" in source
    assert validates_wording(variable, source)
    shortened = source.replace("If you identify with fewer than ", "For ")
    shortened = shortened.replace(", please answer 'not applicable'", "")
    assert not validates_wording(variable, shortened)
    actual = context_for_native_item(variable, ("White", "Black", "Other Pacific Islander"))
    assert "Other Pacific Islander" in actual.source
    assert "Guamanian or Chamorro" not in actual.source
    assert "not applicable" in actual.source
    assert validates_wording(variable, actual.source, contract_override=actual)



# Full-model source audit identified the following original shared-card items.
# Every variable stays eligible; no original native answer code is changed.
@pytest.mark.parametrize("variable", [
    "obey", "popular", "thnkself", "workhard", "helpoth",
    "polescap", "confinan", "confed", "letin1", "letin1a",
    "pornlaw", "marblk", "marasian", "marhisp",
    "rateincumb24", "ratechall124", "ratechall224", "ratechall324",
    "ratedemp", "raterepp", "ratemaga",
])
def test_full_native_audit_repairs_verified_shared_context(variable):
    source = context_for(variable).source
    assert validates_standalone(source), variable
    assert validates_wording(variable, source), variable
    assert "..." not in source and "{" not in source
    assert not validates_wording(variable, "Which of the following options is best?")


@pytest.mark.parametrize("variable", ["obey", "popular", "thnkself", "workhard", "helpoth"])
def test_rank_question_preserves_relative_five_attribute_task(variable):
    source = context_for(variable).source
    for phrase in ("to obey", "well-liked", "think for oneself", "work hard", "help others",
                   "most important", "least important"):
        assert phrase in source
    assert not validates_wording(
        variable, "How important is it for a child to obey?"
    ), "Independent importance ratings must not replace relative rankings"


@pytest.mark.parametrize("variable", [
    "rateincumb24", "ratechall124", "ratechall224", "ratechall324",
    "ratedemp", "raterepp", "ratemaga",
])
def test_thermometers_are_not_recast_as_approval_items(variable):
    source = context_for(variable).source
    assert "0 to 100" in source
    assert "50 means neither favorable nor unfavorable" in source
    assert validates_wording(variable, source)
    assert not validates_wording(
        variable, "Do you strongly approve, approve, disapprove, or strongly disapprove?"
    )
