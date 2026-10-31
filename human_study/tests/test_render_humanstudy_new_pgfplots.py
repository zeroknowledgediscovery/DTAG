"""Synthetic regression for the restored 71-session human-study PGFPlots generator.

No source participant data is used or committed.
"""
from __future__ import annotations
import csv
import importlib.util
from pathlib import Path
import pytest

SOURCE=Path(__file__).resolve().parents[1]/"scripts"/"render_humanstudy_new_pgfplots.py"
SPEC=importlib.util.spec_from_file_location("humanstudy_new",SOURCE)
module=importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)

def participant(base, q4_delta, final_delta):
    vals=[base+q4_delta*min(t,4)/4+(final_delta-q4_delta)*max(t-4,0)/16
          for t in range(21)]
    return {"base":base,"index":dict(enumerate(vals)),
            "delta":[v-base for v in vals]}

def synthetic():
    # Left: 17 negative (16 successes), 4 positive (4 successes)
    left=[participant(-.2,-.01,-.04) for _ in range(16)]
    left += [participant(-.2,.01,.01)]
    left += [participant(.2,-.01,-.04) for _ in range(4)]
    # Right: initially Left 17 TP, 2 FP, 10 TN; initially Right 9 responders
    right=[participant(-.2,-.01,-.04) for _ in range(17)]
    right += [participant(-.2,-.01,+.04) for _ in range(2)]
    right += [participant(-.2,+.01,+.04) for _ in range(10)]
    right += [participant(.2,+.01,+.04) for _ in range(9)]
    neutral=[participant(-.1,0,0) for _ in range(6)]
    neutral += [participant(.1,0,0)]
    random=[participant(-.1,0,0) for _ in range(2)]
    random += [participant(.1,0,0) for _ in range(3)]
    return dict(left=left,right=right,neutral=neutral,random=random)

def test_regenerate_new_aggregates(tmp_path):
    module.build(synthetic(),tmp_path,boots=100,seed=101)
    p=tmp_path/"humanstudy_new_arm_summary.csv"
    with p.open(newline="") as f: rows={r["arm"]:r for r in csv.DictReader(f)}
    assert {arm:int(r["n_completed"]) for arm,r in rows.items()}=={
        "left":21,"right":38,"neutral":7,"random":5}
    assert int(rows["left"]["n_directional_success"])==20
    assert int(rows["right"]["n_directional_success"])==21
    for arm in module.ARMS:
        with (tmp_path/f"humanstudy_new_trajectory_{arm}.csv").open() as f:
            rr=list(csv.DictReader(f))
        assert len(rr)==21
        assert int(rr[-1]["n"])==int(rows[arm]["n_completed"])
        assert abs(float(rr[0]["mean"]))<1e-10
        assert (tmp_path/f"humanstudy_new_endpoint_{arm}.csv").exists()
    table=(tmp_path/"humanstudy_new_table.tex").read_text()
    assert "21" in table and "38" in table
    assert "95" in table
    # Additional figure keeps all 9 initially Right + 10 Q4-unflagged
    # initially Left, excluding 17 TP and 2 FP based only on Q4.
    filtered=tmp_path/"humanstudy_new_trajectory_right_q4_unflagged.csv"
    with filtered.open(newline="") as f:
        q4rows=list(csv.DictReader(f))
    assert [int(r["step"]) for r in q4rows]==list(range(21))
    assert {int(r["n"]) for r in q4rows}=={19}
    assert float(q4rows[0]["mean"])==0
    assert abs(float(q4rows[-1]["mean"])-0.04)<1e-9
    assert float(q4rows[-1]["ci_low"])>0
    # The original Right-push line remains unfiltered (n=38).
    with (tmp_path/"humanstudy_new_trajectory_right.csv").open(newline="") as f:
        right_rows=list(csv.DictReader(f))
    assert int(right_rows[-1]["n"])==38
    assert abs(float(right_rows[-1]["mean"])-float(q4rows[-1]["mean"]))>1e-6


def test_abort_on_wrong_cohort(tmp_path):
    arms=synthetic()
    arms["right"].pop()
    with pytest.raises(ValueError,match="cohort mismatch"):
        module.build(arms,tmp_path,boots=100,seed=101)
    assert not (tmp_path/"humanstudy_new_table.tex").exists()
