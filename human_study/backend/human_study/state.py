"""Pure human observations, with no persona inference, model draws or eviction."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Mapping


@dataclass(frozen=True)
class Observation:
    question_id: str
    variable: str
    native_value: str | None
    phase: str
    missing_reason: str | None = None


@dataclass(frozen=True)
class HumanDTAGState:
    experiment_session_id: str
    model_key: str
    config_hash: str
    provenance: dict
    initial_observed_state: Mapping[str, str]
    observed_state: Mapping[str, str]
    observations: tuple[Observation, ...]
    asked_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    reserved_outcome_ids: tuple[str, ...]
    baseline_index: float
    current_index: float
    version: int = 0

    def as_dict(self):
        return asdict(self)


def initialize_human_state(model_key, observed_baseline, study_config, adapter, session_id):
    if model_key != study_config.model_key:
        raise ValueError("unsupported pilot model")
    baseline = study_config.bank("baseline")
    if [o.variable for o in observed_baseline] != [i.item_id for i in baseline]:
        raise ValueError("baseline must be completed in instrument order")
    s = {}
    for o, item in zip(observed_baseline, baseline):
        validate_observation(o, item, adapter)
        if o.native_value is not None:
            s[o.variable] = o.native_value
    index = adapter.index(s)
    return HumanDTAGState(session_id, model_key, study_config.config_hash, adapter.provenance,
                          dict(s), dict(s), tuple(observed_baseline), tuple(o.variable for o in observed_baseline),
                          tuple(study_config.excluded_ids) + tuple(study_config.ethics_disallowed_ids),
                          tuple(i.item_id for i in study_config.bank("outcome")), index, index)


def validate_observation(o, item, adapter):
    if o.variable != item.item_id or o.phase != item.phase:
        raise ValueError("observation does not match the question")
    if o.native_value is None:
        if item.required or o.missing_reason not in ("skip", "prefer_not_to_answer"):
            raise ValueError("this item requires an answer")
    elif o.native_value not in [c.native_value for c in item.choices] or o.native_value not in adapter.support(o.variable):
        raise ValueError("invalid native category")


def apply_observed_answer(state, question, native_value, adapter, config, *, missing_reason=None):
    v = question["target_variable"]
    if v in state.asked_ids or v in state.reserved_outcome_ids or v in state.excluded_ids:
        raise ValueError("item is answered or reserved")
    item = config.item(v)
    if item.phase != "intervention" or v not in adapter.eligible(config):
        raise ValueError("not an eligible intervention item")
    o = Observation(question["question_id"], v, native_value, "intervention", missing_reason)
    validate_observation(o, item, adapter)
    s = dict(state.observed_state)
    if native_value is not None:
        s[v] = native_value
    after = adapter.index(s)
    result = {"index_before": state.current_index, "index_after": after,
              "observed_conditional_index_delta": after - state.current_index,
              "predicted_model_delta": question["selection"]["expected_delta"],
              "conditional_distribution": question["conditional_distribution"]}
    return replace(state, observed_state=s, observations=state.observations + (o,),
                   asked_ids=state.asked_ids + (v,), current_index=after, version=state.version + 1), result


def reconstruct_state(initial_baseline, events, adapter, config, session_id):
    from .policy import choose_next_item
    state = initialize_human_state(config.model_key, initial_baseline, config, adapter, session_id)
    for event in events:
        question = event["question"]
        recorded = question.get("selection") or {}
        if recorded.get("policy"):
            replay = choose_next_item(state, recorded["policy"], set(), recorded["rng_state_before"], config, adapter)
            if replay.get("variable") != question["target_variable"] or replay.get("eligible_ids") != recorded["eligible_ids"]:
                raise ValueError("incompatible replay: recorded question diverges from the policy/state sequence")
        state, result = apply_observed_answer(state, event["question"], event["native_value"], adapter, config,
                                              missing_reason=event.get("missing_reason"))
        if abs(result["index_after"] - event["index_after"]) > 1e-10:
            raise ValueError("incompatible replay: model, configuration or answer sequence changed")
    return state
