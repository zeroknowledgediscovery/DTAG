"""Explicit local-only computational fixture. This is NOT a native GSS model.

It exists solely for credential-free UI/persistence development. It cannot be
enabled in staging or production and its instrument is not a research bank.
"""
from .study_config import StudyConfig


class LocalFixture:
    provenance = {"model_content_sha256": "local-computational-fixture-not-gss", "code_commit": "local-fixture-v1"}

    def support(self, v):
        return ["yes", "no"] if v in {f"item_{i:02}" for i in range(50)} else []

    def validate_config(self, config):
        for i in config.items:
            if not all(c.native_value in self.support(i.item_id) for c in i.choices):
                raise ValueError("invalid local fixture instrument")

    def eligible(self, config):
        return sorted(i.item_id for i in config.bank("intervention")
                      if i.item_id not in set(config.excluded_ids) | set(config.ethics_disallowed_ids))

    def index(self, state):
        return sum((int(v[-2:])-15) * (1 if a == "yes" else -1) for v, a in state.items()) / 100

    def distributions(self, state, variables):
        p = .3 if len(state) % 2 else .6
        return {v: {"yes": p, "no": 1-p} for v in variables}

    def scores(self, state, candidates):
        from optimizer.one_step_geometry import one_step_geometry
        return one_step_geometry(state, candidates, lambda ss: [self.index(s) for s in ss], self.distributions)


class LocalLLM:
    def generate(self, item):
        return {"displayed_wording": item.original_wording, "question_provenance": {
            "provider": "local-fixture", "llm_id": "fixture", "prompt_version": "1", "input_item_id": item.item_id,
            "mapper_hit": True, "cache_hit": False, "fallback": False}}


def fixture_config():
    return StudyConfig(study_id="local-fixture", consent_text="Internal software demonstration using a mathematical fixture, not GSS or a live research instrument. No compensation is offered. Responses are held only in local test memory and disappear on process restart. Continue only with synthetic test responses.", items=[{
        "item_id": f"item_{i:02}", "original_wording": f"For this software test, would you choose the first option for example topic {i+1}?",
        "choices": [{"native_value": a, "display_label": a.title()} for a in ("yes", "no")],
        "phase": "baseline" if i < 13 else "outcome" if i >= 46 else "intervention"
    } for i in range(50)])
