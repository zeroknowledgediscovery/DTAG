"""Synthetic archive contract for V3 offline report."""
import importlib.util
from pathlib import Path
import pytest

p = Path(__file__).resolve().parents[1] / "scripts" / "analyze_v3_trajectory.py"
spec = importlib.util.spec_from_file_location("analyze_v3_trajectory", p)
v3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v3)


def archive():
    qs = []
    for i in range(8):
        phase = "baseline" if i < 4 else "intervention" if i < 7 else "attention"
        q = {
            "ordinal": i, "phase": phase, "target_variable": f"item_{i}",
            "raw_text_response": f"Written answer number {i}",
            "accepted_assignments": [] if i == 7 else [
                {"variable": f"item_{i}", "native_value": "yes",
                 "confidence": .92, "evidence": "answer"}
            ],
        }
        if i in (4, 5, 6):
            before, after = (.12, .15, .18)[i - 4], (.15, .18, .14)[i - 4]
            q["index_result"] = {
                "index_before": before, "index_after": after,
                "observed_conditional_index_delta": after - before,
                "predicted_model_delta": .03,
            }
        if i == 7:
            q["target_variable"] = "attention_reading"
            q["attention_passed"] = True
        qs.append(q)
    return {
        "study_configuration": {
            "response_mode": "free_text_multi", "initial_steps": 4,
            "intervention_steps": 3,
            "attention_checks": [{"check_id": "attention_reading"}],
        },
        "baseline_index": .12, "final_index": .14, "questions": qs,
    }


def test_v3_index_and_mapping_report():
    points, assignments, attention = v3.analyze(archive())
    assert [x["ideology_index"] for x in points] == [.12, .15, .18, .14]
    assert [x["answered"] for x in points] == [4, 5, 6, 7]
    assert len(assignments) == 7
    assert attention == [{"check_id": "attention_reading", "passed": True}]


def test_v3_detects_bad_delta_and_missing_attention():
    final = archive()
    final["questions"][4]["index_result"]["observed_conditional_index_delta"] = 10
    with pytest.raises(ValueError, match="Inconsistent"):
        v3.analyze(final)
    final = archive()
    final["questions"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        v3.analyze(final)


def test_v3_csv(tmp_path):
    trace, assignments, attention = v3.analyze(archive())
    v3.write_csv(tmp_path / "trace.csv", trace)
    v3.write_csv(tmp_path / "assignments.csv", assignments)
    v3.write_csv(tmp_path / "attention.csv", attention)
    assert "predicted_single_target_delta" in (tmp_path / "trace.csv").read_text()
    assert "Written answer number 0" in (tmp_path / "assignments.csv").read_text()
    if v3.plot_trajectory(tmp_path / "plot.png", trace):
        assert (tmp_path / "plot.png").stat().st_size > 0
