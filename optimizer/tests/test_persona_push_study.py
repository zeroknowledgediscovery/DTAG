"""Pure statistical and policy-selection tests for the six-persona DTAG study."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dtag_persona_push_study import (
    PAIRS, POLICIES, bootstrap_means, load_personas, stable_seed, summarize,
)


def test_six_pinned_personas():
    p = load_personas(ROOT / "optimizer/personas/gss2024_spectrum.yaml")
    assert len(p) == 6
    assert len({r[0] for r in p}) == 6
    assert [r[1] for r in p].count("right") == 3
    assert [r[1] for r in p].count("left") == 3
    assert [r[0] for r in p] == [v for pair in PAIRS for v in pair]
    assert all("polviews" in r[2] and "partyid" in r[2] for r in p)


def test_bootstrap_deterministic_and_degenerate():
    assert stable_seed(1, "left", 2, "right") == stable_seed(1, "left", 2, "right")
    assert stable_seed(1, "left", 2, "right") != stable_seed(1, "left", 2, "left")
    m, lo, hi = bootstrap_means([3.0] * 15, nboot=200, seed=6)
    assert (m, lo, hi) == (3.0, 3.0, 3.0)
    m, lo, hi = bootstrap_means([1., 2., 3., 4.], nboot=1200, seed=6)
    assert m == pytest.approx(2.5)
    assert lo <= m <= hi


def test_neutral_policy_chooses_min_absolute_expected_drift(monkeypatch):
    from optimizer import one_step_geometry as geom

    fake_world = SimpleNamespace(
        valid=lambda s: (dict(s), []),
        text={"a": "A", "b": "B"},
    )
    rows = [
        {"variable": "a", "answer": "yes", "conditional_probability": 1.,
         "I_after": .4, "delta_I": .4},
        {"variable": "b", "answer": "yes", "conditional_probability": 1.,
         "I_after": .01, "delta_I": .01},
    ]
    summary = [{"variable": "a", "expected_delta": .4, "P_up": 1.,
                "P_down": 0., "one_sided": True, "range": 0.},
               {"variable": "b", "expected_delta": .01, "P_up": 1.,
                "P_down": 0., "one_sided": True, "range": 0.}]
    monkeypatch.setattr(geom, "strict_native_index", lambda world, state: 0.)
    monkeypatch.setattr(
        geom, "native_one_step",
        lambda *args, **kwargs: SimpleNamespace(summary=summary, rows=rows,
                                                 extremes={"argmax_mu": summary[0],
                                                           "argmin_mu": summary[1]}),
    )
    out = geom.policy_run(fake_world, {}, "right", 1,
                          np.random.default_rng(5),
                          policy="neutral_mu", only=["a", "b"])
    assert len(out) == 1
    assert out[0]["variable"] == "b"
    assert out[0]["expected_delta"] == pytest.approx(.01)


def test_all_policies_have_stepwise_CIs_and_paired_contrasts():
    persons = [("a", "right", {"polviews": "conservative"}, ""),
               ("b", "left", {"polviews": "liberal"}, "")]
    rows = []
    for name, side, _, _ in persons:
        for rep in range(8):
            for arm in POLICIES:
                shift = {"right": .10, "left": -.10, "neutral": 0., "random": .01}[arm]
                for t in (0, 1, 2):
                    rows.append({"persona": name, "lean": side, "policy": arm,
                                 "rep": rep, "step": t,
                                 "I": (0.1 if name == "a" else -0.1) + t * shift,
                                 "net_delta": t * shift})
    ci, ends, diffs = summarize(rows, persons, 2, 8, 200, 27)
    assert len(ci) == 2 * 4 * 3
    assert len(ends) == 2 * 4
    assert len(diffs) == 2 * 3
    right = next(x for x in diffs if x["persona"] == "a" and x["policy"] == "right")
    assert right["mean_difference"] == pytest.approx(.18)
