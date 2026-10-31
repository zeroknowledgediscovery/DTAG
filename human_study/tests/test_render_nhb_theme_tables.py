"""Synthetic tests of NHB theme-table generation (no participant records)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[1]
          / "scripts" / "render_nhb_theme_tables.py")
spec = importlib.util.spec_from_file_location("nhb_theme_tables", SOURCE)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def synthetic():
    topics = {}
    stage = {}
    for group, n, early, late in (
        ("left_all", 21, 0.01, 0.02),
        ("right_all", 38, 0.03, 0.04),
        ("right_initially_left_q4_flagged", 19, -0.03, 0.005),
        ("right_initially_left_q4_unflagged", 10, 0.04, 0.02),
        ("right_initially_right", 9, 0.05, 0.06),
    ):
        for label, value in (("early", early), ("late", late),
                             ("all", early+late)):
            stage[(group, label)] = {
                "group": group, "stage": label, "n_sessions": str(n),
                "mean_signed_displacement": str(value)
            }
    for group, n in (("left_all", 21), ("right_all", 38)):
        counts = [n, n, n, n, n, n, n*14]
        assert sum(counts) == n*20
        for (topic, _), count in zip(mod.TOPICS, counts):
            topics[(group, "all", topic)] = {
                "group": group, "stage": "all", "topic": topic,
                "n_selections": str(count),
                "sum_signed": str((0.03 if group == "left_all" else 0.07)
                                  * n * count/(n*20)),
            }
    for group, _, n in mod.GROUPS:
        topics[(group, "early", "civil_liberties")] = {
            "group": group, "stage": "early", "topic": "civil_liberties",
            "n_selections": str(n), "sum_signed": str(n*0.02),
        }
        if group != "right_initially_right":
            topics[(group, "early", "religion_culture")] = {
                "group": group, "stage": "early", "topic": "religion_culture",
                "n_selections": str(n), "sum_signed": str(-n*0.01),
            }
    return topics, stage


def test_tables_have_exhaustive_theme_counts_and_separate_early_late():
    topics, stages = synthetic()
    t1 = mod.table_one(topics, stages)
    t2 = mod.table_two(topics, stages)
    assert "420 (100" in t1 and "760 (100" in t1
    assert "Religion and culture" in t1
    assert "Civil liberties" in t1
    assert "Initially Left, Q4-flagged" in t2
    assert "Initially Left, Q4-unflagged" in t2
    assert "Initially Right" in t2
    assert "---" in t2  # suppressed early religion row is not assumed zero
    assert t1.count(r"\begin{table}") == 1
    assert t2.count(r"\begin{table}") == 1


def test_abort_when_theme_totals_do_not_reproduce_endpoint():
    topics, stages = synthetic()
    topics[("left_all", "all", "other")]["sum_signed"] = "0.8"
    with pytest.raises(ValueError, match="consistency check"):
        mod.table_one(topics, stages)


def test_abort_when_a_theme_is_missing_or_q4_stages_do_not_telescope():
    topics, stages = synthetic()
    topics.pop(("left_all", "all", "religion_culture"))
    with pytest.raises(ValueError, match="seven exhaustive themes"):
        mod.table_one(topics, stages)
    topics, stages = synthetic()
    stages[("right_initially_left_q4_flagged", "all")]["mean_signed_displacement"] = "0.1"
    with pytest.raises(ValueError, match="consistency check"):
        mod.table_two(topics, stages)
