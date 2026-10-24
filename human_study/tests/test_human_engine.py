import copy
import os
from dataclasses import replace

import pytest

from human_study.policy import POLICIES, choose_next_item, initial_rng
from human_study.state import Observation, apply_observed_answer, initialize_human_state, reconstruct_state
from human_study.questions import QuestionLLM


def baseline(config):
    return [Observation(f"b{i}", item.item_id, "yes", "baseline") for i, item in enumerate(config.bank("baseline"))]


def initial(config, adapter):
    return initialize_human_state(config.model_key, baseline(config), config, adapter, "anonymous-fixture")


@pytest.mark.parametrize("policy", POLICIES)
def test_twenty_step_replay_and_no_synthetic_paths(instrument, adapter, monkeypatch, policy):
    import dtag_core as core
    from dtag_session import DTAGSession
    def forbidden(*a, **kw):
        raise AssertionError("synthetic response path called")
    for name in ("responses_for_vars_from_distributions", "llm_craft_human_answer", "llm_persona_to_assignments"):
        monkeypatch.setattr(core, name, forbidden)
    monkeypatch.setattr(DTAGSession, "_initialize", forbidden)
    outputs = []
    events = []
    for replay in range(2):
        state = initial(instrument, adapter)
        rng = initial_rng(763)
        trace = []
        for step in range(20):
            selection = choose_next_item(state, policy, set(), rng, instrument, adapter)
            rng = selection["rng_state"]
            question = {"question_id": str(step), "target_variable": selection["variable"],
                        "selection": selection, "conditional_distribution": {
                            r["answer"]: r["conditional_probability"] for r in selection["per_answer"]}}
            answer = "yes" if step % 3 else "no"  # recorded fixture responses, no model draws
            state, result = apply_observed_answer(state, question, answer, adapter, instrument)
            trace.append((question["target_variable"], state.current_index))
            if replay == 0:
                events.append({"question": question, "native_value": answer, "index_after": state.current_index})
        outputs.append(trace)
        assert len(state.observed_state) == 33  # no state_keep eviction
        assert state.current_index == adapter.index(state.observed_state)
    assert outputs[0] == outputs[1]
    reconstructed = reconstruct_state(baseline(instrument), events, adapter, instrument, "anonymous-fixture")
    assert reconstructed.current_index == outputs[0][-1][1]
    events[0]["index_after"] += 1
    with pytest.raises(ValueError, match="incompatible replay"):
        reconstruct_state(baseline(instrument), events, adapter, instrument, "anonymous-fixture")


def test_policies_reference_pool_and_scores(instrument, adapter):
    state = initial(instrument, adapter)
    candidates = {v: adapter.support(v) for v in adapter.eligible(instrument)}
    scores = adapter.scores(dict(state.observed_state), candidates)
    for policy, key in [("right", lambda r: (-r["expected_delta"], r["variable"])),
                        ("left", lambda r: (r["expected_delta"], r["variable"])),
                        ("neutral", lambda r: (abs(r["expected_delta"]), r["variable"]))]:
        pick = choose_next_item(state, policy, set(), initial_rng(42), instrument, adapter)
        expected = min(scores.summary, key=key)
        assert pick["variable"] == expected["variable"]
        assert pick["expected_delta"] == expected["expected_delta"]
        assert pick["eligible_ids"] == sorted(candidates)
        assert not set(pick["eligible_ids"]) & set(state.reserved_outcome_ids + state.asked_ids)


def test_validation_exhaustion_missing_and_no_baseline_persona(instrument, adapter):
    state = initial(instrument, adapter)
    with pytest.raises(ValueError, match="completed"):
        initialize_human_state(instrument.model_key, [], instrument, adapter, "s")
    pick = choose_next_item(state, "right", set(), initial_rng(1), instrument, adapter)
    q = {"question_id": "q", "target_variable": pick["variable"], "selection": pick,
         "conditional_distribution": {"yes": .3, "no": .7}}
    for invalid in ("YES", "invented", None):
        with pytest.raises(ValueError):
            apply_observed_answer(state, q, invalid, adapter, instrument)
    state2, _ = apply_observed_answer(state, q, "yes", adapter, instrument)
    with pytest.raises(ValueError, match="answered"):
        apply_observed_answer(state2, q, "yes", adapter, instrument)
    with pytest.raises(ValueError, match="reserved"):
        apply_observed_answer(state, {**q, "target_variable": state.reserved_outcome_ids[0]}, "yes", adapter, instrument)
    exhausted = choose_next_item(state, "random", set(adapter.eligible(instrument)), initial_rng(1), instrument, adapter)
    assert exhausted["status"] == "no_candidate" and exhausted["reason"]
    with pytest.raises(ValueError, match="unknown instrument"):
        apply_observed_answer(state, {**q, "target_variable": "unknown"}, "yes", adapter, instrument)


def test_llm_generation_mapping_and_bounded_fallback(instrument, adapter, monkeypatch):
    import dtag_core as core
    import optimizer.dtag_bridge as bridge
    adapter.world = object()
    item = instrument.bank("intervention")[0]
    calls = []
    monkeypatch.setattr(core, "llm_craft_survey_question", lambda *a: calls.append(a) or "Actual generated neutral question?")
    monkeypatch.setattr(bridge, "map_question", lambda *a: {"variables": [item.item_id]})
    llm = QuestionLLM(adapter, instrument)
    out = llm.generate(item)
    assert out["displayed_wording"] == "Actual generated neutral question?"
    assert out["question_provenance"]["mapper_hit"] and not out["question_provenance"]["fallback"]
    monkeypatch.setattr(bridge, "map_question", lambda *a: {"variables": ["wrong", item.item_id]})
    out = llm.generate(item)
    assert out["displayed_wording"] == item.original_wording
    assert out["question_provenance"]["fallback"] and len(out["question_provenance"]["attempts"]) == 2


def test_incomplete_source_llm_completion_is_validated_and_never_falls_back(instrument, adapter, monkeypatch):
    import dtag_core as core
    import optimizer.dtag_bridge as bridge
    from human_study.questions import QuestionGenerationError
    adapter.world = object()
    source = "Some people believe the government should"
    item = instrument.bank("intervention")[0].model_copy(update={
        "original_wording": source, "source_text_incomplete": True,
    })
    seen = []
    def generate(*args, **kwargs):
        seen.append(kwargs)
        return "Should the government increase support for this service?"
    monkeypatch.setattr(core, "llm_craft_survey_question", generate)
    monkeypatch.setattr(bridge, "map_question", lambda *a: {"variables": [item.item_id]})
    llm = QuestionLLM(adapter, instrument)
    out = llm.generate(item)
    assert seen == [{"source_incomplete": True}]
    assert out["displayed_wording"] != source
    assert out["question_provenance"]["wording_status"] == "llm_completion_of_unverified_excerpt"
    assert not out["question_provenance"]["fallback"]

    # The shared DTAG helper returns its source input on API errors.
    # A known excerpt must NOT be shown to the respondent in that case.
    monkeypatch.setattr(core, "llm_craft_survey_question", lambda *a, **kw: source)
    with pytest.raises(QuestionGenerationError, match="complete"):
        llm.generate(item)
    # Off-target responses are also forbidden, even if grammatically complete.
    monkeypatch.setattr(core, "llm_craft_survey_question", generate)
    monkeypatch.setattr(bridge, "map_question", lambda *a: {"variables": ["item_47"]})
    with pytest.raises(QuestionGenerationError, match="validated"):
        llm.generate(item)


def test_study_excerpt_flags_preserve_source_and_native_categories():
    from pathlib import Path
    from human_study.study_config import StudyConfig
    from human_study.instrument import INCOMPLETE_GSS_2024
    config = StudyConfig.load(Path(__file__).resolve().parents[1] / "config/study.example.yaml")
    assert len(INCOMPLETE_GSS_2024) == 25
    assert {i.item_id for i in config.items if i.source_text_incomplete} == INCOMPLETE_GSS_2024
    assert len(config.bank("intervention")) == 28
    assert len([i for i in config.bank("intervention") if i.source_text_incomplete]) == 24
    assert config.item("eqwlth").original_wording.endswith("government should")
    assert config.item("workhard").original_wording == "to work hard"
    assert [c.native_value for c in config.item("eqwlth").choices]


def test_real_native_index_and_withheld_predictions():
    from pathlib import Path
    root = Path(os.environ.get("DTAG_MODEL_ROOT", "/nonexistent"))
    if not (root / "gss/gss_2024/trees/binary").is_dir():
        pytest.skip("native GSS 2024 artifact is not installed; see onboarding network requirement")
    from types import SimpleNamespace
    from human_study.adapter import NativeAdapter
    from human_study.instrument import build
    import dtag_core as core
    adapter = NativeAdapter(SimpleNamespace(model_key="gss/gss_2024", model_release="v0.2.1"))
    config = build(adapter)
    observations = [Observation(str(i), item.item_id, item.choices[0].native_value, "baseline")
                    for i, item in enumerate(config.bank("baseline"))]
    state = initialize_human_state(config.model_key, observations, config, adapter, "native-test")
    w = adapter.world
    row = core.build_full_vector_from_state(w.m, dict(state.observed_state), w.ctx.idx_map)
    dl, dr = w.m.distances_to_state(w.g.sL, w.g.sR, row)
    assert state.current_index == pytest.approx((dl-dr)/w.g.dLR, abs=1e-12)
    outcomes = [i.item_id for i in config.bank("outcome")]
    dists = adapter.distributions(dict(state.observed_state), outcomes)
    assert set(dists) == set(outcomes)
    for v, probabilities in dists.items():
        assert sum(probabilities.values()) == pytest.approx(1, abs=1e-8)
        assert set(probabilities) <= set(adapter.support(v))


@pytest.mark.parametrize("policy", POLICIES)
def test_real_native_twenty_observed_answer_replay(policy):
    from pathlib import Path
    root = Path(os.environ.get("DTAG_MODEL_ROOT", "/nonexistent"))
    if not (root / "gss/gss_2024/trees/binary").is_dir():
        pytest.skip("native GSS 2024 artifact is not installed")
    from human_study.adapter import NativeAdapter
    from human_study.study_config import StudyConfig
    config = StudyConfig.load(Path(__file__).resolve().parents[1] / "config/study.example.yaml")
    native = NativeAdapter(config)
    native.validate_config(config)
    observations = [Observation(str(i), item.item_id, item.choices[0].native_value, "baseline")
                    for i, item in enumerate(config.bank("baseline"))]
    state = initialize_human_state(config.model_key, observations, config, native, "native-replay-test")
    rng, events = initial_rng(481), []
    for step in range(20):
        chosen = choose_next_item(state, policy, set(), rng, config, native)
        rng = chosen["rng_state"]
        question = {"question_id": str(step), "target_variable": chosen["variable"], "selection": chosen,
                    "conditional_distribution": {r["answer"]: r["conditional_probability"] for r in chosen["per_answer"]}}
        # A fixed recorded fixture choice, independent of model probabilities or modal labels.
        answer = config.item(chosen["variable"]).choices[step % len(config.item(chosen["variable"]).choices)].native_value
        state, result = apply_observed_answer(state, question, answer, native, config)
        assert result["index_after"] == pytest.approx(native.index(state.observed_state), abs=1e-12)
        events.append({"question": question, "native_value": answer, "index_after": result["index_after"]})
    replayed = reconstruct_state(observations, events, native, config, "native-replay-test")
    assert dict(replayed.observed_state) == dict(state.observed_state)
    assert replayed.current_index == pytest.approx(state.current_index, abs=1e-12)
