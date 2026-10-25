"""V3: evidence-backed multi-variable observations from a single written reply.

This module never calls an LLM. A model may PROPOSE assignments, but the
server validates native support, quoted evidence, confidence and all collisions.
Applied assignments are immutable observational evidence, not synthetic draws.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace

from .state import HumanDTAGState, Observation
from .study_config import digest


def _normalized(text):
    return " ".join(str(text).casefold().split())


def permitted_items(config, adapter):
    """Map only to configured research items; never held-out outcomes or poles."""
    excluded = set(config.excluded_ids) | set(config.ethics_disallowed_ids)
    intervention = set(adapter.eligible(config))
    return {
        item.item_id: item
        for item in config.items
        if item.item_id not in excluded and (
            item.phase == "baseline" or
            (item.phase == "intervention" and item.item_id in intervention)
        )
    }


def prior_baseline_assignments(snap):
    """Reconstitute accepted observations before the baseline state is created."""
    result = {}
    for question in sorted(
        (q for k, q in snap.records.items()
         if k.startswith("questions/") and q.get("status") == "answered"
         and q.get("phase") == "baseline"),
        key=lambda q: q["ordinal"],
    ):
        for assignment in question.get("accepted_assignments", []):
            var = assignment["variable"]
            if var in result and result[var] != assignment["native_value"]:
                raise ValueError("baseline archive contains conflicting accepted assignments")
            result[var] = assignment["native_value"]
    return result


def resolve(response, words, items, existing, adapter, threshold):
    """Validate proposed assignments against raw evidence, support and prior state.

    Each accepted variable is unique; conflicting proposals cannot overwrite
    an observed state. Any invalid/low-confidence mapping is documented as
    rejected, not silently incorporated into the participant's phenotype.
    """
    accepted, rejected, conflicts, confirmations = [], [], [], []
    seen = set()
    if response["status"] != "mapped":
        if response["status"] == "ambiguous":
            from .questions import AnswerNeedsClarification
            raise AnswerNeedsClarification(
                "We could not confidently interpret that response. Please clarify your view."
            )
        return {
            **response, "accepted": accepted, "rejected": rejected,
            "conflicts": conflicts, "confirmations": confirmations,
            "mapping_status": "missing",
        }
    for proposed in response["proposed"]:
        if not isinstance(proposed, dict):
            rejected.append({"proposal": str(proposed)[:100], "reason": "malformed"})
            continue
        variable = str(proposed.get("variable", ""))
        native_value = str(proposed.get("native_value", ""))
        evidence = str(proposed.get("evidence", "")).strip()
        confidence = proposed.get("confidence")
        record = {"variable": variable, "native_value": native_value,
                  "evidence": evidence, "confidence": confidence}
        reason = None
        if variable in seen:
            reason = "duplicate_variable_in_same_response"
        elif variable not in items:
            reason = "unreviewed_or_reserved_variable"
        elif native_value not in {c.native_value for c in items[variable].choices}:
            reason = "category_not_in_approved_item"
        elif native_value not in adapter.support(variable):
            reason = "category_not_supported_by_native_model"
        elif not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or (
            not math.isfinite(confidence) or not 0 <= confidence <= 1
        ):
            reason = "invalid_confidence"
        elif confidence < threshold:
            reason = "below_confidence_threshold"
        elif not evidence or _normalized(evidence) not in _normalized(words):
            reason = "evidence_not_quoted_from_response"
        if reason:
            rejected.append({**record, "reason": reason})
            continue
        seen.add(variable)
        if variable in existing:
            if existing[variable] == native_value:
                confirmations.append({**record, "reason": "consistent_prior_observation"})
            else:
                conflicts.append({
                    **record, "prior_native_value": existing[variable],
                    "reason": "contradicts_prior_observation_not_overwritten",
                })
            continue
        accepted.append(record)
    if not accepted and not confirmations and not conflicts:
        from .questions import AnswerNeedsClarification
        raise AnswerNeedsClarification(
            "No valid survey-category interpretation was supported by your words. "
            "Please clarify your answer."
        )
    return {
        **response, "accepted": accepted, "rejected": rejected,
        "conflicts": conflicts, "confirmations": confirmations,
        "mapping_status": "mapped",
    }


def initial_state(config, adapter, sid, questions):
    """Construct baseline from all explicit assignments in 4 initial responses."""
    baseline = config.bank("baseline")
    if [q["target_variable"] for q in questions] != [item.item_id for item in baseline]:
        raise ValueError("baseline questions must occur in configured order")
    state = {}
    observations = []
    asked = [item.item_id for item in baseline]
    for q in questions:
        for assignment in q.get("accepted_assignments", []):
            v, value = assignment["variable"], assignment["native_value"]
            if v in state:
                raise ValueError("baseline assignment duplicates prior observation")
            state[v] = value
            observations.append(Observation(q["question_id"], v, value, "baseline"))
            if v not in asked:
                asked.append(v)
    index = adapter.index(state)
    return HumanDTAGState(
        sid, config.model_key, config.config_hash, adapter.provenance,
        dict(state), dict(state), tuple(observations), tuple(asked),
        tuple(config.excluded_ids) + tuple(config.ethics_disallowed_ids),
        tuple(item.item_id for item in config.bank("outcome")),
        index, index,
    )


def apply(state, question, assignments, adapter):
    """Atomically condition on all new native observations from this reply."""
    updates = {}
    observations = []
    asked = list(state.asked_ids)
    target = question["target_variable"]
    if target not in asked:
        asked.append(target)
    for row in assignments:
        v, value = row["variable"], row["native_value"]
        if v in state.observed_state or v in updates:
            raise ValueError("cannot overwrite an observed native assignment")
        if v in state.reserved_outcome_ids or v in state.excluded_ids:
            raise ValueError("cannot condition on a reserved or excluded survey item")
        if value not in adapter.support(v):
            raise ValueError("native category is invalid")
        updates[v] = value
        observations.append(Observation(question["question_id"], v, value, "intervention"))
        if v not in asked:
            asked.append(v)
    after_state = {**state.observed_state, **updates}
    after = adapter.index(after_state)
    sel = question["selection"]
    index_result = {
        "index_before": state.current_index,
        "index_after": after,
        "observed_conditional_index_delta": after - state.current_index,
        "predicted_model_delta": sel["expected_delta"],
        "predicted_delta_scope": "selected_target_only",
        "observed_delta_scope": "all_new_explicit_assignments",
        "accepted_variables": list(updates),
        "conditional_distribution": question["conditional_distribution"],
    }
    next_state = replace(
        state, observed_state=after_state,
        observations=state.observations + tuple(observations),
        asked_ids=tuple(asked), current_index=after, version=state.version + 1,
    )
    return next_state, index_result


def replay(config, adapter, final):
    """Recompute V3 LSM trajectory solely from archived accepted observations.

    The original LLM outputs are NEVER rerun or reconstructed from prose.
    All multi-item observations are replayed as one atomic update per question.
    """
    from .policy import choose_next_item

    questions = sorted(final["questions"], key=lambda q: q["ordinal"])
    baseline = [q for q in questions if q["phase"] == "baseline"]
    adaptive = [q for q in questions if q["phase"] == "intervention"]
    if len(baseline) != len(config.bank("baseline")):
        raise ValueError("baseline question count differs from the configured instrument")
    if len(adaptive) != config.intervention_steps:
        raise ValueError("adaptive question count differs from the configured instrument")
    state = initial_state(config, adapter, final.get("session_id", "archive"), baseline)
    if not math.isclose(state.baseline_index, final["baseline_index"], abs_tol=1e-9):
        raise ValueError("V3 baseline ideology differs from the archive")
    trace = [state.baseline_index]
    for q in adaptive:
        recorded = q["selection"]
        predicted = choose_next_item(
            state, recorded["policy"], set(), recorded["rng_state_before"],
            config, adapter,
        )
        if predicted.get("variable") != q["target_variable"]:
            raise ValueError("V3 adaptive replay diverges from archived policy")
        state, result = apply(state, q, q.get("accepted_assignments") or [], adapter)
        if not math.isclose(
            result["index_after"], q["index_result"]["index_after"],
            abs_tol=1e-9,
        ):
            raise ValueError("V3 recomputed trajectory diverges from archive")
        trace.append(state.current_index)
    if not math.isclose(state.current_index, final["final_index"], abs_tol=1e-9):
        raise ValueError("V3 final ideology differs from archive")
    return trace
