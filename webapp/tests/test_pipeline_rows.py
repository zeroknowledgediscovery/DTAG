"""Model rows must carry answer labels of any length (no fixed-width string truncation)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dtag_core as core  # noqa: E402


class _Model:
    feature_names = ["a", "b", "c"]


LONG = "x" * 150 + " (a label longer than 100 characters)"
IDX = {"a": 0, "b": 1, "c": 2}


def test_row_builders_keep_long_labels():
    m = _Model()
    for build in (core.build_full_vector_from_state, core.build_NULL_with_assignments, core.build_pole_vector):
        row = build(m, {"b": LONG, "c": "short"}, IDX)
        assert list(row) == ["", LONG, "short"]


def test_blank_row_is_all_missing():
    assert list(core.blank_row(_Model())) == ["", "", ""]
