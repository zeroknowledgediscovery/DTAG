"""Read V2 archived indices without recomputing the native LSM."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_v2_trajectory.py"
SPEC = importlib.util.spec_from_file_location("analyze_v2_trajectory", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def example_final():
    questions = []
    for i, variable in enumerate(("trust", "fair", "helpful", "health", "natcity", "natheal", "natroad")):
        q = {
            "ordinal": i,
            "phase": "baseline" if i < 4 else "intervention",
            "target_variable": variable,
            "displayed_wording": f"Generated question {i + 1}?",
            "original_wording": f"Canonical question {i + 1}?",
            "raw_text_response": f"My written opinion {i + 1}",
            "response_value": "yes",
            "response_interpretation": {
                "status": "mapped", "confidence": 0.95,
                "reason": "respondent explicitly endorsed category",
            },
        }
        if i >= 4:
            before = (0.2, 0.25, 0.21)[i - 4]
            after = (0.25, 0.21, 0.28)[i - 4]
            q["index_result"] = {
                "index_before": before,
                "index_after": after,
                "observed_conditional_index_delta": after - before,
                "predicted_model_delta": (0.04, 0.01, -0.02)[i - 4],
            }
        questions.append(q)
    return {
        "study_id": "pilot-v2",
        "policy": "right",
        "baseline_index": 0.2,
        "final_index": 0.28,
        "study_configuration": {
            "response_mode": "free_text_llm", "initial_steps": 4,
            "intervention_steps": 3, "items": [{"phase": "baseline"}] * 4,
        },
        "questions": questions,
    }


def test_v2_full_baseline_and_three_observed_states():
    summary, trajectory, evidence = module.analyze(example_final())
    assert len(trajectory) == 4 and len(evidence) == 7
    assert [x["answered"] for x in trajectory] == [4, 5, 6, 7]
    assert [x["ideology_index"] for x in trajectory] == [0.2, 0.25, 0.21, 0.28]
    assert [x["variable"] for x in trajectory] == ["", "natcity", "natheal", "natroad"]
    assert summary["baseline"] == 0.2
    assert summary["final"] == 0.28
    assert summary["total_delta"] == pytest.approx(0.08)
    assert [x["predicted_delta"] for x in trajectory[1:]] == [0.04, 0.01, -0.02]
    assert all(x["written_answer"].startswith("My written opinion") for x in evidence)
    assert all(x["confidence"] == 0.95 for x in evidence)


def test_rejects_missing_trajectory_and_inconsistent_delta():
    archive = example_final()
    archive["questions"][-1].pop("index_result")
    with pytest.raises(ValueError, match="index_result"):
        module.analyze(archive)
    archive = example_final()
    archive["questions"][4]["index_result"]["index_before"] = -1.0
    with pytest.raises(ValueError, match="Noncontiguous"):
        module.analyze(archive)
    archive = example_final()
    archive["questions"][4]["index_result"]["observed_conditional_index_delta"] = 0
    with pytest.raises(ValueError, match="Inconsistent"):
        module.analyze(archive)


def test_rejects_other_studies_and_incomplete_response_text():
    archive = example_final()
    archive["study_configuration"]["response_mode"] = "click"
    with pytest.raises(ValueError, match="V2"):
        module.analyze(archive)
    archive = example_final()
    archive["questions"][2]["raw_text_response"] = None
    with pytest.raises(ValueError, match="Missing raw"):
        module.analyze(archive)


def test_csv_and_plot_outputs(tmp_path):
    summary, points, evidence = module.analyze(example_final())
    module.write_csv(tmp_path / "trajectory.csv", points)
    module.write_csv(tmp_path / "mapping.csv", evidence)
    text = (tmp_path / "trajectory.csv").read_text()
    assert "ideology_index" in text and "0.28" in text
    assert "My written opinion 1" in (tmp_path / "mapping.csv").read_text()
    if module.write_plot(tmp_path / "plot.png", points):
        assert (tmp_path / "plot.png").stat().st_size > 0
