"""Selection alone. PCG64 state is JSON-persistable and never draws an answer."""
import math
import numpy as np

POLICIES = ("right", "left", "neutral", "random")


def initial_rng(seed):
    return np.random.PCG64(seed).state


def choose_next_item(state, policy, exclusions, rng_state, config, adapter):
    if policy not in POLICIES:
        raise ValueError("unknown policy")
    skip = (set(state.asked_ids) | set(state.observed_state) |
            set(state.reserved_outcome_ids) | set(state.excluded_ids) | set(exclusions))
    if config.candidate_mode == "native_webapp":
        # Exactly the web app's askable_items + native_one_step, including
        # the objective selected by its resp_mode (max/modal or draw/mean).
        candidates = adapter.webapp_candidates(
            dict(state.observed_state), config, exclusions=skip
        )
        eligible = sorted(candidates)
        if not eligible:
            return {"status": "no_candidate", "reason": "no remaining webapp-askable native items",
                    "rng_state": rng_state}
        result = adapter.webapp_scores(dict(state.observed_state), candidates)
        if not all(math.isfinite(r["expected_delta"]) and math.isfinite(r["delta_modal"])
                   for r in result.summary):
            raise ValueError("undefined native webapp one-step scores")
        objective = "delta_modal" if config.push_response_mode == "max" else "expected_delta"
        # Match optimizer.session_push.suggest ordering and the webapp's
        # strict sign criterion for right/up and left/down.
        web_ranked = sorted(result.summary, key=lambda r: (r[objective], r["variable"]))
        if policy == "right":
            choices = [r for r in web_ranked[::-1] if r[objective] > 0]
        elif policy == "left":
            choices = [r for r in web_ranked if r[objective] < 0]
        elif policy == "neutral":
            choices = sorted(result.summary,
                             key=lambda r: (abs(r[objective]), r["variable"]))
        else:
            choices = sorted(result.summary, key=lambda r: r["variable"])
        if not choices:
            return {"status": "no_candidate",
                    "reason": f"no webapp-askable item moves toward {policy}",
                    "rng_state": rng_state}
        bit = np.random.PCG64()
        bit.state = rng_state
        pos = int(np.random.Generator(bit).integers(len(choices))) if policy == "random" else 0
        chosen = choices[pos]
        rows = [r for r in result.rows if r["variable"] == chosen["variable"]]
        return {
            "status": "selected", "variable": chosen["variable"], "policy": policy,
            "expected_delta": chosen["expected_delta"],
            "delta_modal": chosen["delta_modal"],
            "predicted_delta": chosen[objective],
            "objective": "modal" if objective == "delta_modal" else "expected",
            "candidate_mode": "native_webapp",
            "eligible_ids": eligible, "top_candidates": choices[:5],
            "per_answer": rows, "rng_state_before": rng_state, "rng_state": bit.state,
            "algorithm": "optimizer.session_push.askable_items + optimizer.one_step_geometry.native_one_step",
        }
    eligible = sorted(set(adapter.eligible(config)) - skip)
    candidates = {v: [c.native_value for c in config.item(v).choices] for v in eligible}
    if not eligible:
        return {"status": "no_candidate", "reason": "eligible unasked pool exhausted", "rng_state": rng_state}
    result = adapter.scores(dict(state.observed_state), candidates)
    if not all(math.isfinite(r["expected_delta"]) for r in result.summary):
        raise ValueError("undefined conditional probabilities; cannot choose an item")
    ranks = {"right": lambda r: (-r["expected_delta"], r["variable"]),
             "left": lambda r: (r["expected_delta"], r["variable"]),
             "neutral": lambda r: (abs(r["expected_delta"]), r["variable"]),
             "random": lambda r: r["variable"]}
    ranked = sorted(result.summary, key=ranks[policy])
    bit = np.random.PCG64()
    bit.state = rng_state
    pos = int(np.random.Generator(bit).integers(len(eligible))) if policy == "random" else 0
    chosen = ranked[pos]
    rows = [r for r in result.rows if r["variable"] == chosen["variable"]]
    return {"status": "selected", "variable": chosen["variable"], "policy": policy,
            "expected_delta": chosen["expected_delta"], "eligible_ids": eligible,
            "top_candidates": ranked[:5], "per_answer": rows,
            "rng_state_before": rng_state, "rng_state": bit.state,
            "algorithm": "exact-one-step-mu-v1; ties=ascending-variable-id; rng=PCG64"}
