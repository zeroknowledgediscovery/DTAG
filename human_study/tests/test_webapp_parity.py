"""Direct algorithm parity with optimizer.session_push and DTAGSession mapping.

No native artifacts or OpenAI required; monkeypatch ONLY native execution and
LLM replies, not the original candidate/ranking or mapper implementations.
"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from human_study.adapter import NativeAdapter
from human_study.policy import choose_next_item, initial_rng
from human_study.response_mapping import map_human_response, shared_session_config
from human_study.state import HumanDTAGState
from human_study.study_config import StudyConfig


def world_and_config(instrument):
    item_ids = [f"item_{i:02}" for i in range(46)]
    var_map = {v: f"Question about topic {v}?" for v in item_ids}
    possible = {v: ["yes", "no"] for v in item_ids}
    ctx = SimpleNamespace(
        idx_map={v: i for i, v in enumerate(item_ids)},
        feat=set(item_ids), var_map=var_map,
        possible=possible, map_path="/test/map.csv",
        assets_dir="/test/assets",
        var_embeddings=lambda *args: {v: [1.0, 0.0] for v in item_ids},
    )
    polar = SimpleNamespace(left_map={}, right_map={})
    world = SimpleNamespace(
        ctx=ctx, g=polar, text=var_map,
        model_path="/test/model", map_path="/test/map.csv",
    )
    config = StudyConfig(
        study_id="webapp-parity-fixture",
        question_mode="llm_required", response_mode="free_text_multi",
        candidate_mode="native_webapp", push_response_mode="draw",
        initial_steps=4, intervention_steps=3,
        items=instrument.bank("baseline")[:4],
    )
    return world, config


def test_webapp_candidates_and_one_step_push_are_identical(
    instrument, adapter, monkeypatch
):
    from optimizer.one_step_geometry import one_step_geometry
    import optimizer.one_step_geometry as geometry
    import optimizer.session_push as push

    world, config = world_and_config(instrument)
    native_adapter = object.__new__(NativeAdapter)
    native_adapter.world = world
    native_adapter.lock = threading.RLock()
    state = {f"item_{i:02}": "yes" for i in range(4)}

    def native_proxy(w, s, *, only=None, exclude=(), exclude_poles=False, **kw):
        variables = (set(w.ctx.idx_map) if only is None else set(only))
        variables -= set(exclude) | set(s)
        return one_step_geometry(
            s, {v: list(w.ctx.possible[v]) for v in sorted(variables)},
            lambda states: [adapter.index(st) for st in states],
            adapter.distributions, text=w.ctx.var_map,
        )
    # Both original webapp and human study call this exact shared function.
    monkeypatch.setattr(geometry, "native_one_step", native_proxy)
    monkeypatch.setattr(push, "native_one_step", native_proxy)

    original_session = SimpleNamespace(
        ctx=world.ctx, polar=world.g, model=object(), state=dict(state),
        ideology_enabled=True, lock=threading.RLock(),
        config=SimpleNamespace(resp_mode="draw", state_keep=1000),
    )
    from optimizer.session_push import askable_items, suggest
    original_vars = askable_items(original_session, include_pole_items=False)
    human_candidates = native_adapter.webapp_candidates(state, config)
    assert sorted(human_candidates) == original_vars

    native_state = HumanDTAGState(
        "s", config.model_key, config.config_hash, native_adapter.provenance
        if hasattr(native_adapter, "provenance") else {},
        state, state, (), tuple(state), (), (),
        adapter.index(state), adapter.index(state),
    )
    original_push = suggest(original_session, include_pole_items=False,
                            mode="realistic")
    assert original_push["objective"] == "expected"
    for direction, original_label in [("right", "up"), ("left", "down")]:
        selected = choose_next_item(
            native_state, direction, set(), initial_rng(100),
            config, native_adapter,
        )
        webapp = original_push[original_label]
        assert selected["status"] == "selected"
        assert selected["variable"] == webapp["variable"]
        assert selected["expected_delta"] == pytest.approx(webapp["expected_delta"])
        assert selected["predicted_delta"] == pytest.approx(webapp["predicted_delta"])
        assert selected["objective"] == webapp["objective"]

    # Candidate geometry is recomputed from the *new* state after observation.
    moved = {**state, "item_45": "yes"}
    assert "item_45" not in native_adapter.webapp_candidates(moved, config)


def test_written_response_uses_DTAGSession_map_question_unchanged(
    instrument, monkeypatch
):
    from dtag_session import DTAGSession
    world, _ = world_and_config(instrument)
    response = "I favor this topic and also topic 19."
    question = "Question about topic item_12?"
    text = question + "\n" + response

    class Client:
        def __init__(self):
            self.calls = []
            self.responses = self

        def create(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs["text"]["format"]["name"] == "variable_selection"
            return SimpleNamespace(output_text=json.dumps({
                "variables": ["item_12", "item_19"],
                "rationale": "two explicit topics",
            }))

    client = Client()
    shared_cfg = shared_session_config("test-model")
    assert shared_cfg.resp_mode == "draw"
    from dtag_config import load_config
    from human_study import ROOT
    run_defaults = load_config(ROOT / "configs/dtag_config.yaml")["defaults"]["run"]
    assert shared_cfg.k == run_defaults["k"]
    assert shared_cfg.prefilter == run_defaults["prefilter"]
    assert shared_cfg.min_map_score == run_defaults["min_map_score"]
    assert shared_cfg.semantic_k == run_defaults["semantic_k"]
    assert shared_cfg.semantic_prefilter == run_defaults["semantic_prefilter"]
    assert shared_cfg.semantic_resp_mode == run_defaults["semantic_resp_mode"]
    assert shared_cfg.semantic_fallback == "update_state"
    from types import SimpleNamespace
    original = DTAGSession.map_question(
        SimpleNamespace(ctx=world.ctx, config=shared_cfg,
                        _client=lambda: client), text,
    )
    actual = map_human_response(world, client, "test-model", question, response)
    assert actual["variables"] == original["variables"] == ["item_12", "item_19"]
    assert actual["path"] == "webapp_direct_mapping"
    assert actual["source"] == "dtag_session.DTAGSession.map_question"
    assert len(client.calls) == 2
    assert client.calls[0]["input"] == client.calls[1]["input"]


def test_embedding_fallback_reuses_DTAGS_original_functions(
    instrument, monkeypatch
):
    import dtag_core as core
    world, _ = world_and_config(instrument)
    calls = []

    def semantic_prefilter(**kwargs):
        calls.append(("semantic_prefilter", kwargs))
        return [("item_22", "question about topic item_22", 0.99)]

    def bridge(**kwargs):
        calls.append(("bridge", kwargs))
        return (["item_22"], "semantically related", [
            {"variable": "item_22", "confidence": 0.95}
        ], True)

    monkeypatch.setattr(core, "semantic_prefilter", semantic_prefilter)
    monkeypatch.setattr(core, "llm_select_semantic_bridge_variables", bridge)
    result = map_human_response(
        world, object(), "test-model",
        "qzvwx invented words with no matching map terms?",
        "zrxvnf phrasing that lexical mapping cannot recognize",
    )
    assert result["variables"] == ["item_22"]
    assert result["path"] == "webapp_semantic_update_state"
    assert [x[0] for x in calls] == ["semantic_prefilter", "bridge"]
    assert calls[-1][1]["min_confidence"] == shared_session_config(
        "test-model"
    ).semantic_min_confidence


def test_native_mode_requires_no_YAML_adaptive_items(instrument):
    _, config = world_and_config(instrument)
    assert config.bank("intervention") == []
    assert config.candidate_mode == "native_webapp"
    assert config.push_response_mode == "draw"


def test_native_pole_audit_compares_canonical_request_and_resolved_wave(monkeypatch):
    """Regression for false mismatch when DTAG remaps canonical GSS poles to 2024."""
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    import numpy as np
    import dtag_session
    from human_study import ROOT
    from dtag_engine import POLAR_VECTOR_SETS

    path = ROOT / "human_study/scripts/audit_webapp_native_parity.py"
    spec = importlib.util.spec_from_file_location("audit_webapp_native_parity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    canonical = (ROOT / POLAR_VECTOR_SETS["gss_default"]["path"]).resolve()
    wave = (ROOT / "assets/polar_vectors/gss/gss_2024_polar_vectors.csv").resolve()
    geometry = SimpleNamespace(
        enabled=True, disable_reason="",
        requested_path=str(canonical), path=str(wave),
        left_map={"test": "left"}, right_map={"test": "right"},
        sL=np.array([1., 0.]), sR=np.array([0., 1.]), dLR=1.2,
    )
    adapter = SimpleNamespace(world=SimpleNamespace(ctx=object(), g=geometry))
    calls = []
    def shared_builder(ctx, polar_path):
        calls.append(polar_path)
        return geometry

    monkeypatch.setattr(dtag_session, "build_polar_geometry", shared_builder)
    requested, resolved = module.verify_webapp_poles(adapter)
    assert requested == canonical
    assert resolved == wave
    assert calls == [str(canonical)]

    # Supplying only the resolved path, as the previous broken audit assumed,
    # is NOT equivalent to using the webapp's registered polar configuration.
    geometry.requested_path = str(wave)
    with pytest.raises(AssertionError, match="requested pole set mismatch"):
        module.verify_webapp_poles(adapter)

    # Even a correct requested file is not sufficient if effective poles differ.
    geometry.requested_path = str(canonical)
    geometry.path = str(canonical)
    with pytest.raises(AssertionError, match="resolved pole set mismatch"):
        module.verify_webapp_poles(adapter)
