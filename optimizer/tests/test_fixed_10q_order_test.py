"""Regression tests for fixed-set 10-question order experiment (no native model)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts import dtag_fixed_10q_order_test as test


def test_precommitted_fixed_sets_are_valid():
    entries=test.read_sets(test.DEFAULT_SETS)
    assert len(entries)==18
    assert {r["source_policy"] for r in entries} == {"right","left","neutral"}
    assert len({r["persona"] for r in entries}) == 6
    for row in entries:
        assert len(row["questions"]) == len(set(row["questions"])) == 10
        assert set(row["source_answers"])==set(row["questions"])


def test_deterministic_ordering_and_common_question_draws():
    q=[f"q{x}" for x in range(10)]
    a=test.order_permutations(q,"p","right",123)
    b=test.order_permutations(q,"p","right",123)
    assert a==b
    assert a["original"]==tuple(q)
    assert a["reverse"]==tuple(reversed(q))
    assert len(set(a.values()))==4
    assert all(set(v)==set(q) for v in a.values())
    assert test.seed_for(1,"p","right",0,"q1")==test.seed_for(1,"p","right",0,"q1")


class FakeWorld:
    def valid(self, state):
        return dict(state), []

    def I(self, state):
        # Function of final assignment only; by definition insensitive to order.
        return 0.3 + sum(1.0 for k,v in state.items()
                         if k=="q1" and v=="positive")

    def dists(self, state, variables):
        v=variables[0]
        if v=="q1":
            # q1 answer changes depending on whether q0 was previously asked.
            return {"q1":{"positive": 1.0} if "q0" in state else {"negative":1.0}}
        return {v:{"known":1.0}}


def test_permutation_changes_generated_answer_but_not_identical_answer_index(monkeypatch):
    monkeypatch.setattr(test, "_WORLD", FakeWorld())
    q=tuple(f"q{x}" for x in range(10))
    answers={v:("positive" if v=="q1" else "known") for v in q}
    a=test._job(("p","right",{},answers,"original",q,0,123))[0]
    b=test._job(("p","right",{},answers,"reverse",q[::-1],0,123))[0]
    assert a["final_I"] == pytest.approx(1.3)
    assert b["final_I"] == pytest.approx(.3)
    assert a["fixed_answer_control_I"]==pytest.approx(b["fixed_answer_control_I"])
    assert a["fixed_answer_control_error"] == pytest.approx(0.0)


def test_bootstrap_and_paired_contrasts():
    endpoints=[]
    for rep in range(20):
        for name,move in zip(test.ORDER_NAMES,[0,.03,0,-.04]):
            endpoints.append({
                "persona":"p","source_policy":"left","rep":rep,
                "order":name,"initial_I":-.25,"final_I":-.25+move,
                "net_delta":move,
                "answer_map":'{"q0":"known"}',
            })
    ep,dif,om=test.summarize(endpoints,20,200,123)
    assert len(ep)==4 and len(dif)==3 and len(om)==1
    assert {x["order"]:x["mean_final_I_difference"] for x in dif} == pytest.approx(
        {"reverse":.03,"shuffle1":0,"shuffle2":-.04})
    assert om[0]["max_minus_min_order_mean"]==pytest.approx(.07)
