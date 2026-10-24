#!/usr/bin/env python3
"""Compare saved absolute ideology displacement; never invokes the native LSM.

The archive is a 20-question, 40-repetition GSS2024 experiment, even though
its original local run directory was named 'test_q3_r2'.
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_RUN = ROOT / "data" / "order_20q_r40"
POLICIES = ("right", "left", "neutral")
ORDERS = ("original", "reverse", "shuffle1", "shuffle2")
PEOPLE = (
    ("cm_rural_alabama", "Alabama"),
    ("wf_new_york_city", "New York"),
    ("religious_conservative_woman_texas", "Texas"),
    ("secular_liberal_man_seattle", "Seattle"),
    ("hispanic_catholic_man_arizona", "Arizona"),
    ("black_churchgoing_woman_atlanta", "Atlanta"),
)


def read(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def f(r, key):
    return float(r[key])


def analyze(run_dir, dest, plot=True):
    adaptive = read(run_dir / "adaptive" / "endpoints.csv")
    order = read(run_dir / "order" / "endpoint_summary.csv")
    paired = read(run_dir / "order" / "paired_order_contrasts.csv")
    manifest_path = run_dir / "order" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if manifest and (manifest.get("questions_per_run") != 20 or manifest.get("repetitions") != 40):
        raise ValueError("Expected archived 20-question, 40-repetition run")
    ai = {(r["persona"], r["policy"]): r for r in adaptive}
    oi = {(r["persona"], r["source_policy"], r["order"]): r for r in order}
    pi = {(r["persona"], r["source_policy"], r["order"]): r for r in paired}
    if len(ai) != 24 or len(oi) != 72 or len(pi) != 54:
        raise ValueError("Incomplete or duplicate archived summary records")
    records = []
    for person, label in PEOPLE:
        for policy in POLICIES:
            a = ai[person, policy]
            original = oi[person, policy, "original"]
            base = f(original, "initial_I")
            if abs(base - f(a, "initial_I")) > 1e-8:
                raise ValueError("Different initial ideology; check model provenance")
            for pos in ORDERS:
                r = oi[person, policy, pos]
                drift = f(r, "mean_net_delta")
                if abs(f(r, "mean_final_I") - f(r, "initial_I") - drift) > 1e-8:
                    raise ValueError("Inconsistent replay drift")
                if abs(f(r, "initial_I") - base) > 1e-8:
                    raise ValueError("Replay baselines differ")
                contrast = drift - f(original, "mean_net_delta")
                if pos == "original":
                    ci_d = (0., 0.)
                else:
                    p = pi[person, policy, pos]
                    if abs(f(p, "mean_final_I_difference") - contrast) > 1e-8:
                        raise ValueError("Absolute replay means disagree with paired contrast")
                    ci_d = (f(p, "ci_low"), f(p, "ci_high"))
                records.append(dict(
                    persona=person, label=label, policy=policy, order=pos,
                    reps=int(r["reps"]), initial_I=base,
                    adaptive_mean=f(a, "mean_delta"),
                    adaptive_ci_low=f(a, "ci_low"), adaptive_ci_high=f(a, "ci_high"),
                    replay_mean=drift, replay_ci_low=f(r, "ci_low"),
                    replay_ci_high=f(r, "ci_high"),
                    replay_CI_excludes_zero=(f(r, "ci_low") > 0 or f(r, "ci_high") < 0),
                    order_minus_original=contrast,
                    difference_ci_low=ci_d[0], difference_ci_high=ci_d[1],
                    difference_CI_excludes_zero=(ci_d[0] > 0 or ci_d[1] < 0),
                ))
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "absolute_order_displacements.csv"
    with out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    result = {}
    for policy in POLICIES:
        result[policy] = {}
        for pos in ORDERS:
            rr = [r for r in records if r["policy"] == policy and r["order"] == pos]
            result[policy][pos] = {
                "mean_of_six_persona_means": sum(r["replay_mean"] for r in rr) / len(rr),
                "pointwise_95pct_CI_excludes_zero": sum(r["replay_CI_excludes_zero"] for r in rr),
                "personas": len(rr),
            }
    report = dict(native_evaluations=0, source_run=str(run_dir), manifest=manifest,
                  interpretation="Uses existing per-order pointwise bootstrap intervals, not new tests",
                  counts=result)
    (dest / "order_drift_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        fig, ax = plt.subplots(figsize=(9.3, 7))
        labels = [(name, policy) for name, _ in PEOPLE for policy in ("right", "left")]
        y = np.arange(len(labels))[::-1]
        idx = {(r["persona"], r["policy"], r["order"]): r for r in records}
        for label, order_name, dy, mark in (
            ("Adaptive selection", None, .22, "o"),
            ("Frozen original", "original", 0, "s"),
            ("Frozen reverse", "reverse", -.22, "D"),
        ):
            vals, low, high = [], [], []
            for name, policy in labels:
                d = idx[name, policy, order_name or "original"]
                prefix = "adaptive" if order_name is None else "replay"
                vals.append(d[prefix + "_mean"])
                low.append(d[prefix + "_ci_low"])
                high.append(d[prefix + "_ci_high"])
            a, lo, hi = np.array(vals), np.array(low), np.array(high)
            ax.errorbar(a, y + dy, xerr=[np.maximum(0, a - lo), np.maximum(0, hi - a)],
                        marker=mark, linestyle="none", capsize=2, ms=4, label=label)
        ax.axvline(0, linewidth=1, linestyle="--", color="gray")
        ax.set_yticks(y, [f"{dict(PEOPLE)[p]} / {pol}" for p, pol in labels])
        ax.set_xlabel("Mean ideology displacement from identical baseline (95% bootstrap CI)")
        ax.set_title("20-question adaptive vs frozen/reversed question sequences")
        ax.grid(axis="x", alpha=.2)
        ax.legend()
        fig.tight_layout()
        fig.savefig(dest / "absolute_order_displacements.pdf")
        fig.savefig(dest / "absolute_order_displacements.png", dpi=170)
        plt.close(fig)
    for p in POLICIES:
        print(p, {order: result[p][order] for order in ORDERS})
    print("Native model calls: 0. Outputs:", dest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "order_20q_r40" / "postprocess")
    parser.add_argument("--no-plot", action="store_true")
    a = parser.parse_args()
    analyze(a.run_dir, a.out, not a.no_plot)
