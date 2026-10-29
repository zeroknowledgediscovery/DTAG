"""Offline tests for Q3/Q4 early phenotype and held-out directional prediction."""
import importlib.util
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[1] / "scripts" / "analyze_push_phenotypes.py"
spec = importlib.util.spec_from_file_location("analyze_push_phenotypes", script)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def trajectory(after, last, *, k=4, initial=-0.4):
    t = [initial] + [0.1] * 20
    t[k] = after
    t[-1] = last
    return t


def test_early_phenotype_uses_absolute_early_index():
    t = trajectory(-0.05, -0.10, initial=-0.4)
    x = analysis.example(t, "left", "calibrated", 4)
    assert x["phenotype"] == "left"  # not sign(index_after_Q4 - calibrated_baseline)
    assert x["later_delta"] == pytest.approx(-0.05)
    assert x["success"] is True
    assert x["label"] == "left_success"


def test_success_is_subsequent_movement_only():
    t = trajectory(0.05, 0.01, initial=-0.5)
    right = analysis.example(t, "right", "calibrated", 4)
    left = analysis.example(t, "left", "calibrated", 4)
    assert right["phenotype"] == "right"
    assert right["later_delta"] == pytest.approx(-0.04)
    assert not right["success"] and right["label"] == "right_fail"
    assert left["success"] and left["label"] == "left_success"


def test_features_do_not_use_original_calibration_or_party():
    a = analysis.example(trajectory(-0.03, 0.12, initial=-0.25),
                         "right", "calibrated", 4)
    b = analysis.example(trajectory(-0.03, 0.12, initial=+0.25),
                         "right", "no-calibration", 4)
    assert analysis.feature(a) == analysis.feature(b)


def test_loo_scores_and_four_class_labels():
    rows = [
        analysis.example(trajectory(0.1 if i % 3 else -0.05,
                                    0.2 if i % 2 else -0.2),
                         "right" if i % 2 else "left",
                         "calibrated" if i < 6 else "no-calibration", 4)
        for i in range(12)
    ]
    for method in ("policy", "phenotype", "logistic"):
        guesses = analysis.loo(rows, method)
        metrics = analysis.accuracy(guesses)
        assert len(guesses) == 12
        assert all(g["predicted"].startswith(g["policy"] + "_") for g in guesses)
        assert 0 <= metrics["accuracy"] <= 1
        assert 0 <= metrics["brier"] <= 1
        assert metrics["tp"] + metrics["tn"] + metrics["fp"] + metrics["fn"] == 12
    # Empty held-out training group uses a neutral prior, not the test answer.
    assert analysis.predict([], rows[0], "phenotype") == 0.5


def test_fetches_both_policies_and_validates_index_chain(monkeypatch):
    root = analysis.url("proj", "dtag-human-pilot", "test-study")

    # Mock the Firestore REST wire format, not already-decoded Python values.
    # report_left_live.fields() deliberately expects typed Firestore fields.
    def wire(value):
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        if isinstance(value, str):
            return {"stringValue": value}
        if isinstance(value, dict):
            return {"mapValue": {"fields": {k: wire(v) for k, v in value.items()}}}
        raise TypeError(f"Unexpected Firestore fixture value: {type(value).__name__}")

    def wire_doc(data, *, name=None):
        result = {"fields": {k: wire(v) for k, v in data.items()}}
        if name is not None:
            result["name"] = name
        return result

    def header(sid, policy, last):
        return wire_doc({
            "consent_accepted": True, "policy": policy, "next_step": 20,
            "attention_completed": 0,
            "state": {"baseline_index": -0.036, "current_index": last}
        }, name=root + "/" + sid)

    def list_fake(url, _cred, _mask):
        if url == root:
            return [header("one", "left", -0.06),
                    header("two", "right", +0.04)]
        if url.endswith("/questions"):
            last = -0.06 if url.endswith("/one/questions") else 0.04
            trace = [-0.036] + [(-0.036 + (last+0.036)*k/20) for k in range(1, 21)]
            return [wire_doc({"status": "answered", "phase": "intervention",
                              "step": i,
                              "index_result": {"index_before": trace[i],
                                               "index_after": trace[i+1]}})
                    for i in range(20)]
        return []

    monkeypatch.setattr(analysis, "list_docs", list_fake)
    subjects, counts = analysis.retrieve("proj", "dtag-human-pilot", "credential",
                                         {"test-study": (0, "no-calibration")})
    assert len(subjects) == 2
    assert counts[("test-study", "complete_left")] == 1
    assert counts[("test-study", "complete_right")] == 1
    assert {s["policy"] for s in subjects} == {"left", "right"}


def test_wilson_interval_bounds():
    low, high = analysis.wilson(5, 10)
    assert 0 < low < 0.5 < high < 1
