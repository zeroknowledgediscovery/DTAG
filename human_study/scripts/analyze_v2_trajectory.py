#!/usr/bin/env python3
"""Analyze one completed V2 human study archive without recomputing ideology.

Reads immutable final.json either from local disk or from private GCS via ADC.
Writes a local CSV and, if matplotlib is installed, a PNG trajectory. No
participant data is sent to GitHub or any external service by this script.

From DTAG repo root:
    python3 human_study/scripts/analyze_v2_trajectory.py --latest
    python3 human_study/scripts/analyze_v2_trajectory.py --file /tmp/v2-final.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path


def load_latest(bucket: str, study: str) -> dict:
    # Uses investigator's Application Default Credentials, not public access.
    from google.cloud import storage

    client = storage.Client()
    blobs = [
        blob for blob in client.list_blobs(
            bucket, prefix=f"studies/{study}/sessions/"
        ) if blob.name.endswith("/final.json")
    ]
    if not blobs:
        raise ValueError(f"No completed {study} session final.json exists in {bucket}")
    # GCS updated is reliable for selecting the last archived final object.
    blob = max(blobs, key=lambda b: b.updated)
    return json.loads(blob.download_as_bytes())


def finite(value: object, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Missing or invalid {name}: {value!r}") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"Nonfinite {name}: {value!r}")
    return numeric


def analyze(final: dict) -> tuple[dict, list[dict], list[dict]]:
    """Derive baseline and each actual adaptive index from the archive only."""
    config = final["study_configuration"]
    if config.get("response_mode") != "free_text_llm":
        raise ValueError("The selected archive is not a free-text V2 study")
    questions = sorted(final["questions"], key=lambda q: q["ordinal"])
    n_initial = int(config.get("initial_steps") or sum(
        i["phase"] == "baseline" for i in config["items"]
    ))
    n_adaptive = int(config["intervention_steps"])
    initials = [q for q in questions if q["phase"] == "baseline"]
    adaptive = [q for q in questions if q["phase"] == "intervention"]
    if len(initials) != n_initial or len(adaptive) != n_adaptive:
        raise ValueError(
            f"Archive incomplete: expected {n_initial} initial + {n_adaptive} adaptive; "
            f"found {len(initials)} + {len(adaptive)}"
        )

    baseline = finite(final["baseline_index"], "baseline_index")
    points = [{
        "stage": "Baseline",
        "answered": n_initial,
        "adaptive_step": 0,
        "ideology_index": baseline,
        "observed_delta": "",
        "predicted_delta": "",
        "variable": "",
    }]
    evidence = []
    for q in questions:
        interpretation = q.get("response_interpretation") or {}
        if q.get("raw_text_response") is None:
            raise ValueError(f"Missing raw written response for item {q['target_variable']}")
        evidence.append({
            "question_number": int(q["ordinal"]) + 1,
            "phase": q["phase"],
            "variable": q["target_variable"],
            "question": q["displayed_wording"],
            "written_answer": q["raw_text_response"],
            "native_category": q.get("response_value") or "(unmapped/missing)",
            "confidence": interpretation.get("confidence", ""),
            "mapping_status": interpretation.get("status", ""),
            "interpretation_reason": interpretation.get("reason", ""),
        })

    current = baseline
    for step, q in enumerate(adaptive, 1):
        index = q.get("index_result")
        if not isinstance(index, dict):
            raise ValueError(f"No LSM index_result on adaptive item {q['target_variable']}")
        before = finite(index.get("index_before"), f"step {step} index_before")
        after = finite(index.get("index_after"), f"step {step} index_after")
        delta = finite(index.get("observed_conditional_index_delta"),
                       f"step {step} observed_conditional_index_delta")
        predicted = finite(index.get("predicted_model_delta"),
                           f"step {step} predicted_model_delta")
        if not math.isclose(before, current, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError(f"Noncontiguous trajectory before adaptive step {step}")
        if not math.isclose(after - before, delta, rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError(f"Inconsistent observed index delta at step {step}")
        points.append({
            "stage": f"Adaptive {step}",
            "answered": n_initial + step,
            "adaptive_step": step,
            "ideology_index": after,
            "observed_delta": delta,
            "predicted_delta": predicted,
            "variable": q["target_variable"],
        })
        current = after
    if not math.isclose(
        current, finite(final["final_index"], "final_index"),
        rel_tol=1e-8, abs_tol=1e-8
    ):
        raise ValueError("Trajectory endpoint does not match final_index")
    summary = {
        "study_id": final.get("study_id"),
        "initial_questions": n_initial,
        "adaptive_questions": n_adaptive,
        "policy": final.get("policy", "unknown"),
        "baseline": baseline,
        "final": current,
        "total_delta": current - baseline,
    }
    return summary, points, evidence


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_plot(path: Path, points: list[dict]) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    xs = [p["adaptive_step"] for p in points]
    ys = [p["ideology_index"] for p in points]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(xs, ys, marker="o", linewidth=2)
    ax.axhline(ys[0], linestyle="--", linewidth=1, alpha=0.5)
    ax.set_xticks(xs, ["Baseline"] + [f"After Q{i}" for i in range(1, len(xs))])
    ax.set_xlabel("Adaptive question sequence (following initial questions)")
    ax.set_ylabel("LSM ideology index (native pole-relative convention)")
    ax.set_title("DTAG V2: observed-index trajectory")
    ax.grid(alpha=0.2)
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:+.5f}", (x, y), xytext=(0, 8),
                    textcoords="offset points", ha="center", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", help="local path to completed final.json")
    source.add_argument("--latest", action="store_true", help="latest completed GCS session (default)")
    parser.add_argument("--bucket", default="pkcsaas-01-dtag-study-data")
    parser.add_argument("--study", default="pilot-v2")
    parser.add_argument("--out", default="/tmp/dtag-v2-analysis")
    args = parser.parse_args(argv)
    try:
        final = (json.loads(Path(args.file).read_text(encoding="utf-8"))
                 if args.file else load_latest(args.bucket, args.study))
        summary, points, evidence = analyze(final)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "ideology_trajectory.csv", points)
    write_csv(out / "written_response_mappings.csv", evidence)
    plotted = write_plot(out / "ideology_trajectory.png", points)
    print(f"Study: {summary['study_id']} | policy: {summary['policy']}")
    print(f"Initial: {summary['initial_questions']}; adaptive: {summary['adaptive_questions']}")
    print(f"{'Stage':<14} {'Variable':<12} {'Ideology':>12} {'Actual delta':>14} {'Predicted delta':>16}")
    for row in points:
        obs = f"{row['observed_delta']:+.6f}" if row["adaptive_step"] else "-"
        pred = f"{row['predicted_delta']:+.6f}" if row["adaptive_step"] else "-"
        print(f"{row['stage']:<14} {row['variable']:<12} {row['ideology_index']:+12.6f} "
              f"{obs:>14} {pred:>16}")
    print(f"Total movement from baseline: {summary['total_delta']:+.6f}")
    print("\nWritten response → native LSM assignment:")
    for q in evidence:
        print(f"Q{q['question_number']:02d} [{q['phase']}] {q['variable']}")
        print(f"  Prompt: {q['question']}")
        print(f"  Written: {q['written_answer']}")
        print(f"  Mapped: {q['native_category']} (confidence={q['confidence']}; status={q['mapping_status']})")
        print(f"  Reason: {q['interpretation_reason']}")
    print(f"\nCSV outputs: {out / 'ideology_trajectory.csv'}, {out / 'written_response_mappings.csv'}")
    if plotted:
        print(f"Figure: {out / 'ideology_trajectory.png'}")
    else:
        print("Figure not created (install matplotlib for PNG output).")
    print("Interpretation: model-state conditioning only; not evidence of participant persuasion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
