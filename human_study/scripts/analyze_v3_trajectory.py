#!/usr/bin/env python3
"""Inspect latest V3 ideology trajectory, multi-assignments and attention result.

Uses the stored LSM indices: no invented trajectory or recomputation.
Runs investigator-side using private GCS credentials or a local final.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def load_latest(bucket, study):
    from google.cloud import storage
    client = storage.Client()
    files = [blob for blob in client.list_blobs(
        bucket, prefix=f"studies/{study}/sessions/"
    ) if blob.name.endswith("/final.json")]
    if not files:
        raise ValueError("No completed V3 archive found")
    return json.loads(max(files, key=lambda blob: blob.updated).download_as_bytes())


def analyze(final):
    conf = final["study_configuration"]
    if conf.get("response_mode") != "free_text_multi":
        raise ValueError("Expected V3 free_text_multi archive")
    ordered = sorted(final["questions"], key=lambda q: q["ordinal"])
    baseline = [q for q in ordered if q["phase"] == "baseline"]
    adaptive = [q for q in ordered if q["phase"] == "intervention"]
    attention = [q for q in ordered if q["phase"] == "attention"]
    initial_count = int(conf.get("initial_steps") or
                        sum(item["phase"] == "baseline" for item in conf["items"]))
    if len(baseline) != initial_count or len(adaptive) != conf["intervention_steps"]:
        raise ValueError("Incomplete baseline or adaptive sequence")
    if len(attention) != len(conf.get("attention_checks") or []):
        raise ValueError("Incomplete attention checks")
    idx = float(final["baseline_index"])
    if not math.isfinite(idx):
        raise ValueError("Invalid baseline index")
    traj = [{"adaptive_step": 0, "answered": initial_count, "variable": "BASELINE",
             "index_before": "", "ideology_index": idx, "observed_delta": "",
             "predicted_single_target_delta": "", "accepted_variables": ""}]
    mappings = []
    prior = idx
    for q in ordered:
        for a in q.get("accepted_assignments") or []:
            mappings.append({
                "question_number": q["ordinal"] + 1,
                "phase": q["phase"], "source_question_variable": q["target_variable"],
                "variable": a["variable"], "native_value": a["native_value"],
                "confidence": a["confidence"], "evidence": a["evidence"],
                "original_written_response": q.get("raw_text_response") or "",
            })
    for n, q in enumerate(adaptive, start=1):
        res = q["index_result"]
        before, after = float(res["index_before"]), float(res["index_after"])
        delta = float(res["observed_conditional_index_delta"])
        if not (math.isfinite(after) and math.isfinite(before)
                and math.isclose(prior, before, abs_tol=1e-8)
                and math.isclose(after - before, delta, abs_tol=1e-8)):
            raise ValueError(f"Inconsistent index accounting at adaptive step {n}")
        traj.append({
            "adaptive_step": n, "answered": initial_count + n,
            "variable": q["target_variable"], "index_before": before,
            "ideology_index": after, "observed_delta": delta,
            "predicted_single_target_delta": float(res["predicted_model_delta"]),
            "accepted_variables": ",".join(
                item["variable"] for item in q.get("accepted_assignments") or []
            ),
        })
        prior = after
    if not math.isclose(prior, float(final["final_index"]), abs_tol=1e-8):
        raise ValueError("Final index differs from archived trajectory")
    quality = [{
        "check_id": q["target_variable"],
        "passed": bool(q["attention_passed"]),
    } for q in attention]
    return traj, mappings, quality


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        out = csv.DictWriter(f, fieldnames=list(rows[0]))
        out.writeheader()
        out.writerows(rows)


def plot_trajectory(path, traj):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(7, 4))
    xs = [v["adaptive_step"] for v in traj]
    ys = [v["ideology_index"] for v in traj]
    ax.plot(xs, ys, marker="o")
    ax.axhline(ys[0], linestyle="--", alpha=0.5)
    ax.set_xticks(xs, ["Baseline"] + [f"After Q{i}" for i in xs[1:]])
    ax.set_ylabel("Native LSM pole-relative ideology index")
    ax.set_title("V3: combined multi-observation ideology trajectory")
    ax.grid(alpha=0.2)
    for x, y in zip(xs, ys):
        ax.annotate(f"{y:+.5f}", (x, y), xytext=(0, 8),
                    textcoords="offset points", ha="center")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", help="local path to completed V3 final.json")
    parser.add_argument("--bucket", default="pkcsaas-01-dtag-study-data")
    parser.add_argument("--study", default="pilot-v3")
    parser.add_argument("--out", default="/tmp/dtag-v3-analysis")
    args = parser.parse_args()
    try:
        final = json.loads(Path(args.file).read_text()) if args.file else load_latest(
            args.bucket, args.study)
        trajectory, mappings, quality = analyze(final)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    dest = Path(args.out).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest / "trajectory.csv", trajectory)
    write_csv(dest / "multi_assignments.csv", mappings)
    write_csv(dest / "attention.csv", quality)
    plot_trajectory(dest / "trajectory.png", trajectory)
    print("LSM ideology trajectory (observed multi-item delta; predicted target-only delta)")
    for q in trajectory:
        print(q)
    print("\nWritten-response assignments:")
    for a in mappings:
        print(a)
    print("\nAttention (never applied to LSM):", quality)
    print("\nOutput directory:", dest)


if __name__ == "__main__":
    main()
