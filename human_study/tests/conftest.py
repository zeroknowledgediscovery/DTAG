import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "human_study/backend"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from human_study.study_config import StudyConfig


@pytest.fixture(autouse=True)
def isolate_deployment_origin(monkeypatch):
    """Tests should not inherit the live Cloud Run URL from a deploy shell.

    Origin-specific tests explicitly set DTAG_PUBLIC_ORIGIN themselves.
    """
    monkeypatch.delenv("DTAG_PUBLIC_ORIGIN", raising=False)


class FixtureAdapter:
    """Explicit scientific test fixture, never used as a production model."""
    provenance = {"model_content_sha256": "fixture-only", "code_commit": "test"}

    def support(self, v):
        return ["yes", "no"] if v in {f"item_{i:02}" for i in range(50)} else []

    def validate_config(self, config):
        for i in config.items:
            assert all(c.native_value in self.support(i.item_id) for c in i.choices)

    def eligible(self, config):
        return sorted(i.item_id for i in config.bank("intervention")
                      if i.item_id not in set(config.excluded_ids) | set(config.ethics_disallowed_ids))

    def index(self, state):
        return sum((int(v[-2:]) - 15) * (1 if a == "yes" else -1) for v, a in state.items()) / 100

    def distributions(self, state, variables):
        p = 0.3 if len(state) % 2 else 0.6
        return {v: {"yes": p, "no": 1-p} for v in variables}

    def scores(self, state, candidates):
        from optimizer.one_step_geometry import one_step_geometry
        return one_step_geometry(state, candidates, lambda ss: [self.index(s) for s in ss], self.distributions)


class FixtureLLM:
    def __init__(self):
        self.calls = 0

    def generate(self, item):
        self.calls += 1
        return {"displayed_wording": f"{item.original_wording} (wording {self.calls})", "question_provenance": {
            "provider": "fixture", "llm_id": "fixture-v1", "prompt_version": "1", "input_item_id": item.item_id,
            "mapper_hit": True, "cache_hit": False, "fallback": False}}


@pytest.fixture
def instrument():
    return StudyConfig(study_id="test-study", items=[{
        "item_id": f"item_{i:02}", "original_wording": f"Question about topic {i}?",
        "choices": [{"native_value": a, "display_label": a.title()} for a in ("yes", "no")],
        "phase": "baseline" if i < 13 else "outcome" if i >= 46 else "intervention"
    } for i in range(50)])


@pytest.fixture
def adapter():
    return FixtureAdapter()
