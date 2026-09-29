#!/usr/bin/env python3
"""Benchmark the persistent bundled DTAG native LSM runtime without an LLM."""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from dtag_paths import model_path
from model_backend import load_model


def timed(fn, reps: int):
    vals = []
    result = None
    for _ in range(reps):
        t0 = time.perf_counter()
        result = fn()
        vals.append(time.perf_counter() - t0)
    return result, vals


def summarize(label: str, vals: list[float]) -> None:
    print(
        f"{label:24s} "
        f"min={min(vals):.4f}s "
        f"median={statistics.median(vals):.4f}s "
        f"max={max(vals):.4f}s"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model",
        default=str(model_path("gss", "gss_2024")),
        help="native model directory",
    )
    ap.add_argument("--target", default="immassim")
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()

    model_dir = Path(args.model).expanduser().resolve()

    t0 = time.perf_counter()
    model = load_model(model_dir, backend="native_lsm")
    load_s = time.perf_counter() - t0

    print("model:", model_dir)
    print("runtime:", getattr(model, "runtime_kind", "unknown"))
    print("features:", len(model.feature_names))
    print("usable trees:", len(model.usable_tree_ids))
    print(f"session load/preload:       {load_s:.4f}s")

    target = args.target
    if target not in model.feature_names:
        target = model.feature_names[model.usable_tree_ids[0]]
        print(f"requested target unavailable; using: {target}")

    row = [""] * len(model.feature_names)

    _, pred_times = timed(
        lambda: model.predict_distributions(row, target_names=[target]),
        args.reps,
    )
    summarize(f"predict[{target}]", pred_times)

    _, q_times = timed(
        lambda: model.qdistance(row, row),
        max(1, min(args.reps, 3)),
    )
    summarize("qdistance(NULL,NULL)", q_times)

    _, ideol_times = timed(
        lambda: model.distances_to_state(row, row, row),
        max(1, min(args.reps, 3)),
    )
    summarize("two pole distances", ideol_times)


if __name__ == "__main__":
    main()
