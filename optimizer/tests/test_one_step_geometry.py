"""One-step geometry core on a toy model (no native runtime).  pytest -q optimizer/tests"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from optimizer.one_step_geometry import one_step_geometry  # noqa: E402

# Toy index: additive per-answer weights, plus 0.01 for each assigned variable (a
# "question effect" every answer shares).
W = {"x": {"lo": -0.2, "hi": 0.3}, "y": {"a": 0.05, "b": 0.06}, "z": {"p": 0.0, "q": -0.4}}
P = {"x": {"lo": 0.5, "hi": 0.5}, "y": {"a": 0.9, "b": 0.1}, "z": {"p": 0.75, "q": 0.25, "junk": 9.0}}


def index_fn(states):
    return [0.1 + sum(W.get(v, {}).get(a, 0.0) + 0.01 for v, a in s.items()) for s in states]


def dist_fn(state, variables):
    return {v: dict(P[v]) for v in variables}


@pytest.fixture
def res():
    cands = {"x": ["lo", "hi"], "y": ["a", "b"], "z": ["p", "q"], "known": ["u"]}
    return one_step_geometry({"known": "u"}, cands, index_fn, dist_fn, I_empty=0.1, pole_items={"z"})


def test_rows_and_known_answers_skipped(res):
    assert len(res.rows) == 6 and {r["variable"] for r in res.rows} == {"x", "y", "z"}
    assert res.I_before == pytest.approx(0.11) and res.J_before == pytest.approx(0.01)
    for r in res.rows:
        assert r["delta_I"] == pytest.approx(W[r["variable"]][r["answer"]] + 0.01)
        assert r["J_after"] - r["J_before"] == pytest.approx(r["delta_I"], abs=1e-15)


def test_expectations_and_probability_renormalized_on_valid_labels(res):
    s = {r["variable"]: r for r in res.summary}
    assert s["x"]["expected_delta"] == pytest.approx(0.5 * -0.19 + 0.5 * 0.31)
    assert s["z"]["expected_delta"] == pytest.approx(0.75 * 0.01 + 0.25 * -0.39)  # 'junk' ignored
    assert s["y"]["sd"] == pytest.approx(math.sqrt(0.9 * 0.1 * 0.01 ** 2))
    assert s["y"]["one_sided"] and s["y"]["P_up"] == pytest.approx(1.0)
    assert not s["x"]["one_sided"] and s["x"]["P_down"] == pytest.approx(0.5)
    assert s["z"]["is_pole_item"] and not s["x"]["is_pole_item"]


def test_extremes(res):
    e = res.extremes
    assert e["argmax_mu"]["variable"] == "y"            # mu_y = 0.061 > mu_x = 0.06
    assert e["argmin_mu"]["variable"] == "z"
    assert (e["argmax_delta"]["variable"], e["argmax_delta"]["answer"]) == ("x", "hi")
    assert e["argmax_delta"]["probability"] == pytest.approx(0.5)
    assert (e["argmin_delta"]["variable"], e["argmin_delta"]["answer"]) == ("z", "q")
    assert e["argmax_p_up"]["variable"] == "y" and e["argmax_p_down"]["variable"] == "x"
    assert [r["variable"] for r in res.top("expected_delta", 2)] == ["y", "x"]


def test_nonfinite_index_raises():
    with pytest.raises(FloatingPointError):
        one_step_geometry({}, {"x": ["lo"]}, lambda ss: [float("nan") if s else 0.0 for s in ss], dist_fn)


# ----------------------------------------------------------------- native (skipped without model)

def _gss2018_world():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import fetch_models
        from dtag_paths import model_root
        if not fetch_models.installed(model_root(), "gss/gss_2018"):
            return None
        from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model
        w = World(str(ensure_model("gss/gss_2018", None, download=False)), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), str(Path(tempfile.gettempdir()) / "dtag_test_native_cache"))
    except Exception:
        return None
    return w if getattr(w.m, "has_extension_distances", False) else None


_W2018 = _gss2018_world()


@pytest.mark.skipif(_W2018 is None, reason="gss/gss_2018 not installed or native binding lacks extension_distances")
def test_native_fast_extensions_bit_exact():
    from optimizer.one_step_geometry import native_one_step
    state = {"polviews": "conservative", "partyid": "strong republican", "sex": "male"}
    # relsprt has a 112-character label (exercises the no-truncation row builder)
    only = ["relsprt", "abany", "god", "PRES16", "pistol", "MAOCC10", "coeduc"]
    fast = native_one_step(_W2018, state, only=only, fast=True)
    slow = native_one_step(_W2018, state, only=only, fast=False)
    assert fast.I_before == slow.I_before
    assert [(r["variable"], r["answer"], r["I_after"], r["conditional_probability"]) for r in fast.rows] == \
           [(r["variable"], r["answer"], r["I_after"], r["conditional_probability"]) for r in slow.rows]
    assert any(len(r["answer"]) > 100 for r in fast.rows)
