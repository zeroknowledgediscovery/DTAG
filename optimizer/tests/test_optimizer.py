"""Optimizer tests.  Run from the repo root:  pytest -q optimizer/tests

The first group needs no model. The native smoke test runs only when gss/gss_2024 is installed
(it never downloads); set DTAG_MODEL_ROOT if your models live outside the default cache.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from optimizer import llm as L  # noqa: E402
from optimizer.search import group_stats, objective  # noqa: E402

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "array"}}, "required": ["a", "b"]}


def test_parse_json_tolerates_fences_and_prose():
    assert L.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert L.parse_json('Sure! Here it is: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(Exception):
        L.parse_json("no json here")


def test_default_for_schema():
    assert L._default_for(SCHEMA) == {"a": 0, "b": []}


def test_make_llm_rejects_unknown_provider():
    with pytest.raises(ValueError):
        L.make_llm({"provider": "nope"})


def test_command_provider_and_dtag_client(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import sys, json; sys.stdin.read(); print('ok: ' + json.dumps({'a': 3, 'b': ['x']}))\n")
    llm = L.make_llm({"provider": "command", "command": f"{sys.executable} {script}"})
    assert json.loads(llm.complete("hi", schema=SCHEMA)) == {"a": 3, "b": ["x"]}
    client = L.DTAGClient(llm)
    r = client.responses.create(model="m", input="hi", text={"format": {"type": "json_schema", "name": "x", "schema": SCHEMA}})
    assert json.loads(r.output_text)["a"] == 3


def test_python_provider(tmp_path, monkeypatch):
    (tmp_path / "my_agent.py").write_text(
        "def complete(prompt, schema=None, schema_name='r', temperature=0.2):\n    return '{\"a\": 5, \"b\": []}'\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    llm = L.make_llm({"provider": "python", "callable": "my_agent:complete"})
    assert json.loads(llm.complete("x", schema=SCHEMA))["a"] == 5


def test_mock_rewrite_echoes_items():
    llm = L.make_llm({"provider": "mock"})
    out = json.loads(llm.complete("ITEMS:\n- natenvir\tSpending on the environment\tx; y\n", schema=SCHEMA,
                                  schema_name="question_rewrite"))
    assert out["questions"] == [{"variable": "natenvir", "question": "Spending on the environment"}]


def test_group_stats_and_objective():
    people = [{"direction": 1}, {"direction": -1}, {"direction": 0}]
    runs = [(0, {}, 0.1, 1), (0, {}, 0.1, 2), (1, {}, -0.1, 3), (1, {}, -0.1, 4), (2, {}, 0.0, 5)]
    finals = [[0.1, 0.2], [0.1, 0.3], [-0.1, -0.15], [-0.1, -0.3], [0.0, 1.0]]
    st = group_stats(people, runs, finals)
    assert st["positive"]["n"] == 2 and st["negative"]["n"] == 2  # neutral run excluded
    assert st["positive"]["mean_signed_change"] == pytest.approx(0.15)
    assert st["negative"]["mean_signed_change"] == pytest.approx(0.125)
    assert st["positive"]["share_outward"] == 1.0
    assert objective(st, "robust") == pytest.approx(min(st["positive"]["t"], st["negative"]["t"]))


def test_bank_load_file(tmp_path):
    from optimizer import bank

    p = tmp_path / "b.csv"
    p.write_text("question,source_variables\nShould taxes go up?,tax;natfare\nAnother one?,\n")
    rows = bank.load_file(str(p))
    assert rows[0]["question"] == "Should taxes go up?" and rows[0]["source_variables"] == ["tax", "natfare"]
    assert len(rows) == 2


def _installed():
    try:
        import fetch_models
        from optimizer.dtag_bridge import dtag_model_root
        return bool(fetch_models.installed(dtag_model_root(), "gss/gss_2024"))
    except Exception:
        return False


@pytest.mark.skipif(not _installed(), reason="gss/gss_2024 model not installed")
def test_native_smoke(tmp_path):
    from optimizer.__main__ import main

    seq = tmp_path / "seq.csv"
    seq.write_text("step,question,variables\n1,Should the government reduce income differences?,eqwlth\n"
                   "2,Spending on welfare,natfare\n3,Should abortion be legal for any reason?,abany\n")
    out = tmp_path / "out"
    main(["validate", "--provider", "mock", "--quick", "--workers", "2", "--out", str(out), "--sequence", str(seq)])
    val = json.loads((out / "validation.json").read_text())
    s = val["summary"]
    assert s["positive"]["n"] > 0 and s["negative"]["n"] > 0
    assert np.isfinite(s["separation_change_ci"][0])
    assert (out / "report.md").is_file() and (out / "manifest.json").is_file()


def test_actual_starting_sign_overrides_original_persona():
    from optimizer.search import run_direction, group_stats
    people = [{"direction": 1}, {"direction": -1}]
    runs = [(0, {}, -0.08, 11, "a"), (1, {}, 0.09, 12, "b")]
    final = [[-0.08, -0.12], [0.09, 0.14]]
    assert run_direction(runs[0]) == -1
    assert run_direction(runs[1]) == 1
    stats = group_stats(people, runs, final)
    assert stats["positive"]["mean_signed_change"] == pytest.approx(0.05)
    assert stats["negative"]["mean_signed_change"] == pytest.approx(0.04)


def test_persona_text_assets_and_reference_state():
    from optimizer.population import load
    people = load("optimizer/personas/gss2024_asset_cm_wf.yaml")
    assert len(people) == 2
    assert "Alabama" in people[0]["text"] and "New York City" in people[1]["text"]
    assert people[0]["expected_state"]["polviews"] == "conservative"
    assert people[1]["expected_state"]["partyid"] == "strong democrat"


def test_answer_never_overwrites_protected_anchors():
    import random
    from types import SimpleNamespace
    from optimizer.simulate import answer

    class FakeWorld:
        ctx = SimpleNamespace(idx_map={"polviews": 0, "other": 1})
        def dists(self, state, variables):
            assert "polviews" not in variables
            return {v: {"old": 0, "new": 1} for v in variables}

    state = {"polviews": "conservative", "other": "old"}
    result = answer(FakeWorld(), state, ["polviews", "other"], "draw",
                    random.Random(2), {"polviews": "conservative"})
    assert result["polviews"] == "conservative"
    assert result["other"] == "new"


def test_state_level_diagnostics_do_not_count_draws_as_independent_states():
    from optimizer.evaluate import state_diagnostics
    people = [{"id": "cm", "direction": 1}, {"id": "wf", "direction": -1}]
    runs, trajectories = [], []
    for i, i0, state_id in [(0, .12, "cm:0"), (0, .15, "cm:1"),
                             (1, -.12, "wf:0"), (1, -.17, "wf:1")]:
        for draw in range(12):
            runs.append((i, {}, i0, draw, state_id))
            delta = .03 if i == 0 else -.02
            trajectories.append([i0, i0 + delta])
    rows, diag = state_diagnostics(people, runs, trajectories, 1, np.random.default_rng(8))
    assert len(rows) == 4 and diag["n_states"] == 4
    assert diag["groups"]["positive"]["n_states"] == 2
    assert diag["groups"]["negative"]["n_states"] == 2
    assert diag["groups"]["positive"]["mean_signed_change_ci"][0] == pytest.approx(.03)
    assert diag["groups"]["negative"]["mean_signed_change_ci"][0] == pytest.approx(.02)


def test_multi_state_validation_writes_auditable_outputs(tmp_path):
    from types import SimpleNamespace
    from optimizer.__main__ import validate_and_report

    people = [{"id": "cm", "I0": .12, "direction": 1,
               "protected_values": {"polviews": "conservative"}},
              {"id": "wf", "I0": -.14, "direction": -1,
               "protected_values": {"polviews": "extremely liberal"}}]
    bank = [{"id": "a", "question": "Question A", "variables": ["qa"], "mapping": "source"},
            {"id": "b", "question": "Question B", "variables": ["qb"], "mapping": "source"}]
    cfg = {"participants": {"neutral_band": .005}, "search": {"resp_mode": "draw", "objective": "robust"},
           "bank": {"source": "map", "mapping": "source"},
           "validate": {"reps": 3, "states_per_persona": 2, "reps_per_state": 3,
                        "augment_count": 0, "order_baselines": 0, "seed": 45,
                        "baselines": 0, "baseline_reps": 2}}

    class Sim:
        def make_runs(self, persons, reps, seed, **kw):
            runs = []
            for i, index in enumerate((.12, -.14)):
                for state_num in range(2):
                    for j in range(reps):
                        runs.append((i, dict(persons[i]["protected_values"]),
                                     index + (state_num*.01 if i == 0 else -state_num*.01),
                                     j, f"{i}:{state_num}"))
            return runs

        def simulate(self, runs, seq_vars, mode, trajectories=False):
            rows = []
            for r in runs:
                change = .02 if r[0] == 0 else -.03
                path = [r[2] + step*change for step in range(len(seq_vars)+1)]
                rows.append(path if trajectories else [path[0], path[-1]])
            return rows

    ctx = SimpleNamespace(
        cfg=cfg, out=tmp_path, world=SimpleNamespace(text={"qa": "A", "qb": "B"}),
        log=lambda _: None,
        manifest=lambda size: {"model": {"key": "gss/gss_2024"},
                               "map": {"file": "test.csv", "sha256": "000000000000000"},
                               "poles": {"file": "poles.csv", "items": 2},
                               "llm": None, "bank_size": size})
    validate_and_report(ctx, Sim(), people, bank, ["a", "b"], 2, {})
    report = (tmp_path / "report.md").read_text()
    assert "Across distinct starting states" in report
    assert "States=4" in report
    assert (tmp_path / "per_state.csv").is_file()
    assert len((tmp_path / "starting_states.jsonl").read_text().splitlines()) == 4
    result = json.loads((tmp_path / "validation.json").read_text())
    assert result["summary"]["positive"]["mean_signed_change_ci"][1] > 0
    assert result["summary"]["negative"]["mean_signed_change_ci"][1] > 0



def test_four_way_regime_classification_without_model(tmp_path):
    """Audit is strictly post hoc: use fabricated saved trajectories, no searches."""
    import numpy as np
    from optimizer.four_way_audit import analyze, QUADRANTS

    assert set(QUADRANTS.values()) == {"divergence", "convergence",
                                       "positive_translation", "negative_translation"}
    for directions, regime in [
        ((1, -1), "divergence"), ((1, 1), "positive_translation"),
        ((-1, -1), "negative_translation"), ((-1, 1), "convergence")]:
        folder = tmp_path / regime
        folder.mkdir()
        trajectories, initial, ids = [], [], []
        for group, value in enumerate((.12, -.12)):
            for state in range(6):
                offset = .001*state if group == 0 else -.001*state
                i0 = value + offset
                for draw in range(4):
                    # Nonzero state-level variation keeps the interval finite.
                    change = .02*directions[group] + .00005*(state-2)
                    trajectories.append([i0, i0+change])
                    initial.append(i0)
                    ids.append(f"{group}:{state}")
        np.savez_compressed(folder / "validation_trajectories.npz",
                            trajectories=np.asarray(trajectories),
                            initial_ideology=np.asarray(initial),
                            state_id=np.asarray(ids))
        result = analyze(folder, seed=1, nboot=500)
        assert result["observed_regime"] == regime
        assert result["status"] == "supported_by_state_bootstrap"
        assert result["n_states"] == 12


def test_four_way_missing_files_not_mislabeled(tmp_path):
    from optimizer.four_way_audit import analyze
    assert analyze(tmp_path)["status"] == "missing_validation"
    assert "observed_regime" not in analyze(tmp_path)
