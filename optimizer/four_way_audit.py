"""Descriptive four-regime evaluation of existing DTAG validation trajectories.

Never searches, builds, or optimizes survey question sequences. Input sequences
must be preselected independently of this analysis.
Usage: python -m optimizer.four_way_audit --catalog optimizer/four_way_catalog.yaml
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import yaml

from .dtag_bridge import REPO

QUADRANTS = {(1, -1): "divergence", (1, 1): "positive_translation",
             (-1, -1): "negative_translation", (-1, 1): "convergence"}


def sign(x):
    return (x > 0) - (x < 0)


def interval(values, rng, nboot=2000):
    v = np.asarray(values, dtype=float)
    if not len(v):
        return None
    mean = float(v.mean())
    if len(v) < 2:
        return {"mean": mean, "low": None, "high": None}
    draws = rng.choice(v, size=(nboot, len(v)), replace=True).mean(axis=1)
    return {"mean": mean, "low": float(np.quantile(draws, .025)),
            "high": float(np.quantile(draws, .975))}


def analyze(directory, seed=20261016, nboot=2000, band=.005):
    directory = Path(directory)
    path = directory / "validation_trajectories.npz"
    if not path.is_file():
        return {"status": "missing_validation", "directory": str(directory)}
    with np.load(path, allow_pickle=False) as data:
        trajectory = np.asarray(data["trajectories"], dtype=float)
        i0 = np.asarray(data["initial_ideology"], dtype=float)
        state_ids = np.asarray(data["state_id"]).astype(str)
    if trajectory.ndim != 2 or trajectory.shape[1] < 2:
        raise ValueError(f"{path}: expected a matrix of trajectories")
    if len(trajectory) != len(i0) or len(i0) != len(state_ids):
        raise ValueError(f"{path}: array lengths differ")
    if not np.isfinite(trajectory).all() or not np.isfinite(i0).all():
        raise ValueError(f"{path}: nonfinite ideology values")
    if not np.allclose(trajectory[:, 0], i0, atol=1e-9):
        raise ValueError(f"{path}: inconsistent initial ideology")
    states = {}
    for idx, sid in enumerate(state_ids):
        row = states.setdefault(sid, {"start": float(i0[idx]), "changes": [],
                                      "crosses": []})
        if not np.isclose(row["start"], i0[idx], atol=1e-10, rtol=0):
            raise ValueError(f"state {sid} has inconsistent starting ideology")
        row["changes"].append(float(trajectory[idx, -1] - i0[idx]))
        row["crosses"].append(bool(i0[idx] * trajectory[idx, -1] < 0))
    rng = np.random.default_rng(seed)
    groups = {}
    for direction, name in ((1, "positive"), (-1, "negative")):
        selected = [r for r in states.values() if sign(r["start"] - band) == 1
                    ] if direction == 1 else [
                    r for r in states.values() if r["start"] < -band]
        means = [float(np.mean(r["changes"])) for r in selected]
        all_changes = [v for r in selected for v in r["changes"]]
        crossings = [v for r in selected for v in r["crosses"]]
        groups[name] = {
            "n_states": len(selected), "n_draws": len(all_changes),
            "raw_change_ci": interval(means, rng, nboot),
            "fraction_states_raw_positive": float(np.mean(np.asarray(means) > 0)) if means else None,
            "fraction_trajectories_raw_positive": float(np.mean(np.asarray(all_changes) > 0)) if all_changes else None,
            "fraction_trajectories_cross_zero": float(np.mean(crossings)) if crossings else None}
    positive, negative = (groups[name]["raw_change_ci"] for name in ("positive", "negative"))
    observed = QUADRANTS.get((sign(positive["mean"]), sign(negative["mean"]))) if positive and negative else None
    supported = bool(positive and negative and all(
        ci["low"] is not None and sign(ci["low"]) == sign(ci["high"]) == sign(ci["mean"])
        for ci in (positive, negative)))
    return {
        "directory": str(directory), "observed_regime": observed,
        "status": "supported_by_state_bootstrap" if supported else "descriptive_only",
        "n_trajectories": len(trajectory), "n_states": len(states),
        "n_neutral_trajectories": int(np.sum(np.abs(i0) < band)),
        "groups": groups}


def audit(catalog_path, out, seed=20261016, nboot=2000):
    config = yaml.safe_load(Path(catalog_path).read_text(encoding="utf-8"))
    cases = config["cases"]
    if len(set(case["id"] for case in cases)) != len(cases):
        raise ValueError("duplicate catalog IDs")
    rows = []
    for j, case in enumerate(cases):
        rows.append({**case, **analyze(case["results_dir"], seed+j, nboot,
                                     float(config.get("neutral_band", .005)))})
    directory = Path(out)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"method": "classification of preselected survey sequences (no optimization)",
               "interpretation": "model-state conditioning, not causal attitude change",
               "cases": rows}
    (directory / "four_way_summary.json").write_text(json.dumps(payload, indent=2))
    table = []
    for row in rows:
        gp = row.get("groups", {})
        a = (gp.get("positive", {}).get("raw_change_ci") or {})
        b = (gp.get("negative", {}).get("raw_change_ci") or {})
        table.append({"id": row["id"], "historical_label": row.get("historical_label", ""),
                      "observed_regime": row.get("observed_regime", ""), "status": row["status"],
                      "positive_raw_mean": a.get("mean"), "positive_ci_low": a.get("low"),
                      "positive_ci_high": a.get("high"),
                      "negative_raw_mean": b.get("mean"), "negative_ci_low": b.get("low"),
                      "negative_ci_high": b.get("high"),
                      "distinct_states": row.get("n_states")})
    with (directory / "four_way_summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, list(table[0]) if table else ["id"])
        writer.writeheader()
        writer.writerows(table)
    lines = ["# Four-way LSM response-regime audit", "",
             "Historical labels are not new results. Classification uses RAW ideology-index",
             "changes and a state-cluster bootstrap. No new sequence optimization was performed.", "",
             "| Input | Historical label | Observed regime | Status | Positive raw change | Negative raw change |",
             "|---|---|---|---|---:|---:|"]
    for row in table:
        def f(value):
            return f"{value:+.5f}" if value is not None else "—"
        lines.append(f"| {row['id']} | {row['historical_label']} | "
                     f"{row['observed_regime'] or 'not established'} | {row['status']} | "
                     f"{f(row['positive_raw_mean'])} | {f(row['negative_raw_mean'])} |")
    lines += ["", "The four regimes: divergence (+,-), positive translation (+,+),",
              "negative translation (-,-), convergence (-,+). Convergence is only",
              "inward movement if responses do not overshoot the zero index.",
              "The fraction crossing zero appears in four_way_summary.json.",
              "Rows without trajectory files are unevaluated, not failures.",
              "Starting-state populations may differ between directories; compare only",
              "under documented, matched sampling conditions. These effects describe",
              "inference under a fixed model, not changes in human political beliefs.", ""]
    (directory / "four_way_report.md").write_text("\n".join(lines))
    return payload


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", default=str(REPO / "optimizer" / "four_way_catalog.yaml"))
    p.add_argument("--out", default="outputs/optimizer/four_way_summary")
    p.add_argument("--seed", type=int, default=20261016)
    p.add_argument("--bootstrap", type=int, default=2000)
    args = p.parse_args(argv)
    result = audit(args.catalog, args.out, args.seed, args.bootstrap)
    for row in result["cases"]:
        print(f"{row['id']}: {row.get('observed_regime') or 'not evaluated'} ({row['status']})")
    print(f"wrote {args.out}/four_way_report.md")


if __name__ == "__main__":
    main()
