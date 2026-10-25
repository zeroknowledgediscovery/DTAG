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
