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



def test_multiyear_regime_inventory_reads_preexisting_results(tmp_path):
    from optimizer.multiyear_regime_summary import inventory

    root = tmp_path / "results"
    run = root / "independent_candidate"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"model": {"key": "gss/gss_2016"}}))
    t, starts, ids = [], [], []
    for side, base in ((1, .15), (-1, -.15)):
        for j in range(6):
            x = base + side * .001 * j
            for _ in range(5):
                t.append([x, x + side * .015 + .00001 * j])
                starts.append(x)
                ids.append(f"{side}:{j}")
    np.savez_compressed(run / "validation_trajectories.npz",
                        trajectories=np.asarray(t), initial_ideology=np.asarray(starts),
                        state_id=np.asarray(ids))
    out = tmp_path / "summary"
    summary = inventory(root, out, years=(2016, 2018, 2024), target_per_cell=3,
                        bootstrap=400)
    by_cell = {(row["year"], row["category"]): row for row in summary["coverage"]}
    assert by_cell[(2016, "+-")]["confirmed_runs"] == 1
    assert by_cell[(2016, "+-")]["gap"] == 2
    assert by_cell[(2018, "++")]["confirmed_runs"] == 0
    assert len(summary["runs"]) == 1
    assert (out / "summary.json").is_file()
    assert (out / "coverage_matrix.csv").is_file()
    assert (out / "README.md").is_file()



def test_legacy_trajectory_archive_derives_initial_index(tmp_path):
    """Older npz files sometimes omit the redundant initial_ideology key."""
    from optimizer.four_way_audit import analyze

    folder = tmp_path / "legacy"
    folder.mkdir()
    paths, ids = [], []
    for direction, start in ((1, .1), (-1, -.1)):
        for state in range(6):
            for _ in range(5):
                first = start + direction*.001*state
                paths.append([first, first + direction*(.02 + .0001*state)])
                ids.append(f"{direction}:{state}")
    np.savez_compressed(folder / "validation_trajectories.npz",
                        trajectories=np.array(paths), state_id=np.array(ids))
    result = analyze(folder, seed=3, nboot=400)
    assert result["observed_regime"] == "divergence"
    assert result["status"] == "supported_by_state_bootstrap"
    assert result["initial_ideology_source"] == "trajectories[:,0]"


def test_multiyear_inventory_skips_archive_without_state_ids(tmp_path):
    """Incompatible legacy files must be reported, never cause KeyError or fake CIs."""
    from optimizer.four_way_audit import analyze
    from optimizer.multiyear_regime_summary import inventory

    root = tmp_path / "results"
    folder = root / "old"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"model": {"key": "gss/gss_2024"}}))
    np.savez_compressed(folder / "validation_trajectories.npz",
                        trajectories=np.array([[.1, .2], [-.1, -.2]]))
    checked = analyze(folder)
    assert checked["status"] == "unsupported_schema"
    assert checked["missing_keys"] == ["state_id"]
    report = inventory(root, tmp_path / "audit", years=(2024,), bootstrap=200)
    assert not report["runs"]
    assert len(report["skipped_runs"]) == 1
    assert report["skipped_runs"][0]["status"] == "unsupported_schema"
    assert (tmp_path / "audit" / "skipped_runs.csv").is_file()
    assert report["coverage"][0]["confirmed_runs"] == 0



def test_local_library_neutral_sampling_ignores_requested_direction():
    from optimizer.sequence_library_runner import sample_candidate, candidate_hash
    pool = [{"id": f"item_{n}", "question": f"Item {n}"} for n in range(100)]
    first, digest1 = sample_candidate(pool, 2016, 12, seed=19, existing=set())
    second, digest2 = sample_candidate(pool, 2016, 12, seed=19, existing=set())
    assert first == second and digest1 == digest2
    assert digest1 == candidate_hash(2016, first)
    assert len({q["id"] for q in first}) == 12
    third, digest3 = sample_candidate(pool, 2016, 12, seed=19, existing={digest1})
    assert digest3 != digest1


def test_local_library_prefix_stops_at_sign_neutral_plateau():
    from optimizer.sequence_library_runner import choose_length
    import numpy as np

    starts = np.array([.15] * 8 + [-.15] * 8)
    # Two groups move in opposite directions for 10 steps, then plateau.
    paths = np.tile(starts[:, None], (1, 21))
    for k in range(1, 21):
        if k <= 9:
            delta = np.where(starts > 0, .003, -.003)
        else:
            delta = np.where(starts > 0, .00001, -.00001)
        paths[:, k] = paths[:, k - 1] + delta
    assert choose_length(paths, starts, minimum=10, tolerance=.0001, window=3) == 12
    assert choose_length(paths, starts, minimum=10, tolerance=0, window=2) == 20
    # Does not inspect a requested response quadrant.
    assert choose_length(-paths, -starts, minimum=10, tolerance=.0001, window=3) == 12


def test_local_library_persona_core_protected_and_score():
    from optimizer.sequence_library_runner import derive_spec, score_from_z
    original = [
        {"id": "a", "state": {"polviews": "liberal", "partyid": "strong democrat",
                              "relig": "none", "news": "every day", "age": "35"}},
        {"id": "b", "state": {"polviews": "conservative", "partyid": "republican",
                              "relig": "catholic", "news": "rarely", "age": "60"}}]
    for variant in range(5):
        people = derive_spec(original, variant, seed=10)
        for expected, new in zip(original, people):
            assert set(("polviews", "partyid")) <= set(new["state"])
            assert all(new["state"][k] == expected["state"][k]
                       for k in ("polviews", "partyid"))
    assert score_from_z(3.6) == 4
    assert score_from_z(20.0) == 10
    assert score_from_z(-2.0) == 0



def test_local_library_writes_append_index_with_failed_records(tmp_path):
    from optimizer.sequence_library_runner import write_library_index, load_attempts
    root = tmp_path
    records = [{"run_id": "00001", "year": 2024, "requested_label": "+-",
                "observed_label": "++", "status": "validated",
                "quality_score": 4, "sequence_file": "a.csv"},
               {"run_id": "00002", "year": 2018, "requested_label": "--",
                "status": "failed", "error": "missing model"}]
    write_library_index(root, records)
    import csv
    rows = list(csv.DictReader((root / "library.csv").open()))
    assert len(rows) == 2
    assert rows[0]["observed_label"] == "++"
    assert rows[1]["status"] == "failed"
    assert rows[1]["error"] == "missing model"



def test_crosswave_source_personas_pin_two_core_anchors(tmp_path):
    from optimizer.sequence_library_runner import plain_source_personas
    from optimizer.population import load

    config = tmp_path / "source_personas.yaml"
    plain_source_personas(config)
    people = load(str(config))
    assert len(people) == 2
    for person in people:
        assert person["state"] == {}  # other assignments remain LLM-dependent
        assert set(("polviews", "partyid")) <= set(person["core_expected"])
    assert people[0]["core_expected"]["polviews"] == "conservative"
    assert people[1]["core_expected"]["partyid"] == "strong democrat"


def test_pin_core_anchors_overrides_incomplete_or_incorrect_decoder(tmp_path):
    from types import SimpleNamespace
    from optimizer.population import prepare
    from optimizer.dtag_bridge import JsonCache

    mapfile = tmp_path / "fake_map.csv"
    mapfile.write_text("variable,question\npolviews,views\npartyid,party\n")
    possible = {"polviews": ["conservative", "extremely liberal"],
                "partyid": ["strong republican", "strong democrat"],
                "degree": ["college"]}
    class FakeWorld:
        map_path = str(mapfile)
        model_path = str(tmp_path / "fake_model")
        ctx = SimpleNamespace(possible=possible,
                              idx_map={key: n for n, key in enumerate(possible)})
        def valid(self, values):
            accepted = {k: v for k, v in values.items() if v in possible.get(k, [])}
            return accepted, [k for k in values if k not in accepted]
        def I(self, state):
            return .12 if state["polviews"] == "conservative" else -.12

    records = [
        {"id": "CM", "text": "", "state": {"polviews": "conservative", "degree": "college"},
         "expected_state": {},
         "core_expected": {"polviews": "conservative", "partyid": "strong republican"}},
        {"id": "WF", "text": "", "state": {"polviews": "conservative", "degree": "college"},
         "expected_state": {},
         "core_expected": {"polviews": "extremely liberal", "partyid": "strong democrat"}}
    ]
    messages = []
    result = prepare(FakeWorld(), records, "auto", None, "none", {},
                     JsonCache(tmp_path / "cache.json"), .005, None, 2018,
                     log=messages.append, protect_mapped=False,
                     core_variables=["polviews", "partyid"])
    assert [p["direction"] for p in result] == [1, -1]
    assert [p["protected"] for p in result] == [["partyid", "polviews"]] * 2
    assert result[0]["state"]["partyid"] == "strong republican"
    assert result[1]["state"]["polviews"] == "extremely liberal"
    assert any("pinning" in line for line in messages)


def test_same_sign_models_warn_in_descriptive_mode(tmp_path):
    from types import SimpleNamespace
    from optimizer.population import prepare
    from optimizer.dtag_bridge import JsonCache
    from optimizer.sequence_library_runner import choose_length

    mapfile = tmp_path / "fake_map.csv"
    mapfile.write_text("variable,question\npolviews,views\npartyid,party\n")
    class FakeWorld:
        map_path = str(mapfile)
        model_path = str(tmp_path / "fake_model")
        ctx = SimpleNamespace(possible={"polviews": ["conservative", "extremely liberal"],
                                         "partyid": ["strong republican", "strong democrat"]},
                              idx_map={"polviews": 0, "partyid": 1})
        def valid(self, state):
            return state, []
        def I(self, state):
            return .04 if state["polviews"] == "conservative" else .02

    records = [
        {"id": "CM", "text": "", "state": {"polviews": "conservative",
                                          "partyid": "strong republican"},
         "expected_state": {}, "core_expected": {}},
        {"id": "WF", "text": "", "state": {"polviews": "extremely liberal",
                                          "partyid": "strong democrat"},
         "expected_state": {}, "core_expected": {}}
    ]
    messages = []
    result = prepare(FakeWorld(), records, "auto", None, "none", {},
                     JsonCache(tmp_path / "cache.json"), .005, None, 2018,
                     log=messages.append, protect_mapped=False,
                     core_variables=["polviews", "partyid"], require_both_signs=False)
    assert all(p["direction"] == 1 for p in result)
    assert any("WARNING" in msg and "same" not in msg for msg in messages)
    starts = np.array([.04] * 6 + [.02] * 6)
    paths = np.tile(starts[:, None], (1, 21))
    assert choose_length(paths, starts, minimum=10, tolerance=.0005, window=3) == 10



def test_scratch_2018_pole_inventory_without_native_model(tmp_path):
    """Probes versioned pole CSVs without requiring a native model or network."""
    import importlib.util
    script = REPO / "scratch" / "gss2018_pole_geometry" / "audit.py"
    spec = importlib.util.spec_from_file_location("gss2018_scratch_pole_audit", script)
    assert spec is not None and spec.loader is not None
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    report, wave = audit.inventory(tmp_path)
    assert report["counts"] == {"2016": 34, "2018": 38, "2024": 27}
    assert report["shared_2018_2024"] == 27
    assert len(report["extra_2018"]) == 11
    assert "viruses" in report["extra_2018"]
    assert set(report["different_labels"]) == {"bible", "colcom", "grass", "spkcom"}
    assert {r["item"] for r in report["2018_unresolved"]} == {"prayfreq"}
    assert (tmp_path / "wave_pole_inventory.csv").is_file()
    assert (tmp_path / "v1_v2_changes.csv").is_file()
    assert (tmp_path / "static_summary.json").is_file()


def test_scratch_2018_variant_composition_and_missing_core(tmp_path):
    import importlib.util
    from types import SimpleNamespace
    script = REPO / "scratch" / "gss2018_pole_geometry" / "audit.py"
    spec = importlib.util.spec_from_file_location("gss2018_scratch_pole_audit2", script)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)

    info, waves = audit.inventory(tmp_path)
    # Resolution logic is tested on real model labels in native mode; a
    # canned 2018 support subset tests variant composition and constraints.
    left = {v: r["L"] for v, r in waves[2018].items()}
    right = {v: r["R"] for v, r in waves[2018].items()}
    possible = {k: [left[k], right[k]] for k in left}
    class P:
        map_path = str(REPO / "maps/gss/gss_2018_map.csv")
        ctx = SimpleNamespace(possible=possible)
        g = SimpleNamespace(left_map=left, right_map=right)
    variants, notes = audit.variants(P(), waves)
    assert len(variants["2018_v2_all"][0]) == 38
    assert len(variants["2018_v2_common_with_2024"][0]) == 27
    assert len(variants["2018_v2_without_viruses"][0]) == 37
    assert notes["common_with_2024_pairs"] == 27



def test_2018_model_stratified_pole_construction_uses_conditional_modes():
    import importlib.util
    path = REPO / "scratch" / "gss2018_pole_geometry" / "derive_stratified_poles.py"
    spec = importlib.util.spec_from_file_location("stratified_2018_poles", path)
    module = importlib.util.module_from_spec(spec)
    # The script imports the sibling audit.py. The test loader must use the
    # same module-search semantics as direct CLI execution.
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    left = {
        "a": {"yes": .8, "no": .2},
        "b": {"yes": .55, "no": .45},
        "c": {"yes": .9, "no": .1},
        "d": {"yes": .51, "no": .49},
    }
    right = {
        "a": {"yes": .2, "no": .8},
        "b": {"yes": .45, "no": .55},
        "c": {"yes": .8, "no": .2},
        "d": {"yes": .49, "no": .51},
    }
    L, R, details = module.construct_poles(
        left, right, list(left), min_tv=.05, construction="modal")
    assert L == {"a": "yes", "b": "yes"}
    assert R == {"a": "no", "b": "no"}
    # Contrast poles can differ even when the two groups share the mode.
    lc, rc, contrast = module.construct_poles(
        left, right, list(left), min_tv=.05, construction="contrast")
    assert lc == {"a": "yes", "b": "yes", "c": "yes"}
    assert rc == {"a": "no", "b": "no", "c": "no"}
    assert contrast[2]["left_selected_excess"] == pytest.approx(.1)
    assert contrast[2]["right_selected_excess"] == pytest.approx(.1)
    reasons = {v["variable"]: v["reason"] for v in details}
    assert reasons["c"] == "same_modal_response"
    assert reasons["d"] == "below_min_tv"
    assert module.total_variation(left["a"], right["a"]) == pytest.approx(.6)
    assert module.categorical_mode({"yes": .3, "no": .7})[0] == "no"
    assert module.pole_rows(L, R) == [
        {"variable": "a", "R": "no", "L": "yes"},
        {"variable": "b", "R": "no", "L": "yes"}]
    with pytest.raises(ValueError, match="thresholds"):
        module.construct_poles(left, right, list(left), min_tv=2)


def test_2018_model_stratified_pool_excludes_political_anchors():
    import importlib.util
    from types import SimpleNamespace
    path = REPO / "scratch" / "gss2018_pole_geometry" / "derive_stratified_poles.py"
    spec = importlib.util.spec_from_file_location("stratified_2018_poles_other", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    pole_items = [r["variable"] for r in module.read_csv(
        REPO / "assets/polar_vectors/gss/gss_2018_polar_vectors.csv")]
    possible = {name: ["no", "yes"] for name in pole_items}
    possible["partyid"] = ["strong democrat", "strong republican"]
    possible["polviews"] = ["extremely liberal", "extremely conservative"]
    possible["relig"] = ["none", "protestant"]
    world = SimpleNamespace(ctx=SimpleNamespace(
        idx_map={v: j for j, v in enumerate(possible)}, possible=possible))
    pool = module.response_pool(world, kind="canonical", fixed={"viruses": "true"})
    assert len(pool) == 37
    assert "partyid" not in pool and "polviews" not in pool
    assert "viruses" not in pool
    assert module.fixed_assignments(world, ["relig=none"]) == {"relig": "none"}
    with pytest.raises(ValueError, match="Unsupported"):
        module.fixed_assignments(world, ["relig=unknown"])



def test_scratch_2018_orientation_ties_not_false_success():
    import importlib.util
    path = REPO / "scratch" / "gss2018_pole_geometry" / "derive_stratified_poles.py"
    spec = importlib.util.spec_from_file_location("stratified_2018_poles_ties", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    tied = module.pairwise_orientation([.02123, .02123, .02123, .02123])
    assert tied["pairs"] == 6
    assert tied["ties"] == 6
    assert tied["concordant"] == 0
    assert tied["fraction_concordant_with_half_ties"] == pytest.approx(.5)
    partially = module.pairwise_orientation([1.0, 3.0, 2.0])
    assert partially["concordant"] == 2
    assert partially["discordant"] == 1
    assert partially["fraction_concordant_with_half_ties"] == pytest.approx(2/3)
