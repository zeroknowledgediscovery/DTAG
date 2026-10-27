#!/usr/bin/env python3
"""Curate the human DTAG archive for the manuscript's four-arm PGFPlots figure.

Reads the immutable GCS sessions using plot_human_trajectories.py.
Publishes ONLY Left, Right, Neutral, Random. A participant with policy=right
always contributes to Right; no subgroups are presented in the output.

From the DTAG repository root on a gcloud-authenticated workstation:
  python3 human_study/scripts/render_humanstudy_pgfplots.py

Writes:
  tex/Figures/humanstudy_trajectory_{left,right,neutral,random}.csv
  tex/Figures/humanstudy_endpoint_{left,right,neutral,random}.csv
  tex/Figures/humanstudy_table.tex
  tex/Figures/humanstudy_arm_summary.csv

The PGFPlots source is tex/Figures/humanstudy_figures.tex, committed to git.
Time to completion = final timestamp - session-created timestamp, including
baseline, survey delays, and all 31 question screens. Time is taken from the
reward.created_at and timestamp fields in immutable final.json. This script
fails rather than inventing missing duration records. Only completed sessions
with an observed question-20 index contribute to the endpoint CIs/table.
Partial sessions contribute only observed steps to the trajectories.
All bootstrap intervals are pointwise participant-resampled percentile 95% CIs.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ARMS = ("Left", "Right", "Neutral", "Random")
KEYS = {arm: arm.lower() for arm in ARMS}


def helper_module():
    source = Path(__file__).with_name("plot_human_trajectories.py")
    spec = importlib.util.spec_from_file_location("humanstudy_trajectory_loader", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Missing archived-trajectory loader: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arm_of(name: str) -> str:
    """Normalize stored right-policy records to the single Right display group."""
    if name.strip().lower().startswith("right"):
        return "Right"
    if name in ("Left", "Neutral", "Random"):
        return name
    raise ValueError(f"Unexpected policy group {name!r}")


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Missing ISO 8601 timestamp")
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("Timestamp missing UTC offset")
    return d


def session_minutes(final):
    """Created-at is inside final.reward, not at the top of final.json."""
    start = (final.get("reward") or {}).get("created_at")
    end = final.get("timestamp")
    seconds = (utc_timestamp(end) - utc_timestamp(start)).total_seconds()
    if not (math.isfinite(seconds) and seconds > 0):
        raise ValueError(f"Invalid participant completion duration: {seconds}")
    return seconds / 60.0


def load_times(helper, bucket, sessions, workers):
    complete = [s for s in sessions
                if s["status"] == "COMPLETE" and 20 in s["values"]]
    def fetch(session):
        uri = (f"gs://{bucket}/studies/{session['study_id']}/sessions/"
               f"{session['session_id']}/final.json")
        return (session["study_id"], session["session_id"]), session_minutes(helper.json_object(uri))
    durations = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(fetch, s): s for s in complete}
        for job in as_completed(jobs):
            try:
                key, minutes = job.result()
            except Exception as exc:
                s = jobs[job]
                raise RuntimeError("Unable to determine duration from final.json "
                                   f"for session {s['session_id']}: {exc}") from exc
            durations[key] = minutes
    if len(durations) != len(complete):
        raise ValueError("Duplicate participant-session keys in archived data")
    return durations


def bootstrap_endpoint(values, boots, seed):
    import numpy as np
    a = np.asarray(values, dtype=float)
    if len(a) < 1 or not np.isfinite(a).all():
        raise ValueError("No finite completed endpoints")
    rng = np.random.default_rng(seed)
    samples = rng.choice(a, size=(boots, len(a)), replace=True).mean(axis=1)
    return float(a.mean()), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


def output_csv(path, headings, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headings)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bucket", default="pkcsaas-01-dtag-study-data")
    ap.add_argument("--output-dir", type=Path, default=Path("tex/Figures"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20261027)
    args = ap.parse_args()
    if not 1 <= args.workers <= 32 or args.bootstrap < 100:
        ap.error("workers must be 1..32, bootstrap >=100")
    helper = helper_module()
    sessions = helper.load_sessions(args.bucket, workers=args.workers)
    trajectories = helper.summarize(sessions, boots=args.bootstrap, seed=args.seed)
    durations = load_times(helper, args.bucket, sessions, args.workers)

    # All four policies; cohort identifiers never appear in the published files.
    group_sessions = {g: [] for g in ARMS}
    for s in sessions:
        group_sessions[arm_of(s["group"])].append(s)

    trajectory_by_arm = {}
    for row in trajectories:
        group = arm_of(row["group"])
        if group in trajectory_by_arm:
            raise ValueError(f"Duplicate group in trajectory summary: {group}")
        trajectory_by_arm[group] = row
    if set(trajectory_by_arm) != set(ARMS):
        raise ValueError("Missing policy group from archived trajectories")

    stats = []
    for arm_index, arm in enumerate(ARMS, start=1):
        file_key = KEYS[arm]
        t = trajectory_by_arm[arm]
        counts = t.get("counts", t.get("n_step"))
        if counts is None or len(counts) != 21:
            raise ValueError(f"Invalid time-step counts for {arm}")
        output_csv(
            args.output_dir / f"humanstudy_trajectory_{file_key}.csv",
            ("step", "n", "mean", "ci_low", "ci_high"),
            ((step, counts[step], t["mean"][step], t["low"][step], t["high"][step])
             for step in range(21)),
        )

        complete = [s for s in group_sessions[arm]
                    if s["status"] == "COMPLETE" and 20 in s["values"]]
        if not complete:
            raise ValueError(f"No complete endpoint for policy {arm}")
        vals = [s["values"][20] for s in complete]
        if len(complete) != counts[20]:
            raise ValueError(f"Question-20 population mismatch in {arm}")
        observed = sum(vals) / len(vals)
        if not math.isclose(t["mean"][20], observed, rel_tol=0, abs_tol=1e-10):
            raise ValueError(f"Question-20 mean mismatch for {arm}")

        central, lower, upper = bootstrap_endpoint(vals, args.bootstrap, args.seed + arm_index)
        output_csv(
            args.output_dir / f"humanstudy_endpoint_{file_key}.csv",
            ("x", "n", "mean", "ci_low", "ci_high", "err_minus", "err_plus"),
            [(arm_index, len(complete), central, lower, upper, central - lower, upper - central)],
        )

        pos = sum(s["baseline_index"] > 0 for s in complete)
        neg = sum(s["baseline_index"] < 0 for s in complete)
        zeros = len(complete) - pos - neg
        if zeros:
            raise ValueError(f"{arm} has {zeros} zero-valued baseline indices; table must explicitly account for them")
        time_values = [durations[(s["study_id"], s["session_id"])] for s in complete]
        stats.append({
            "arm": arm, "n": len(complete), "n_neg": neg, "n_pos": pos,
            "mean_minutes": sum(time_values) / len(time_values),
            "mean_change": central, "ci_low": lower, "ci_high": upper,
        })

    output_csv(
        args.output_dir / "humanstudy_arm_summary.csv",
        ("arm", "n_completed", "n_baseline_negative", "n_baseline_positive",
         "mean_completion_minutes", "mean_endpoint_change", "endpoint_ci95_low", "endpoint_ci95_high"),
        ([s[k] for k in ("arm", "n", "n_neg", "n_pos",
                         "mean_minutes", "mean_change", "ci_low", "ci_high")]
         for s in stats),
    )
    table = [
        "% Generated from immutable DTAG GCS sessions by render_humanstudy_pgfplots.py.",
        "% Time is full session wall-clock minutes: created_at to final timestamp.",
        "\\begin{table*}[!t]",
        "\\centering",
        "\\caption{Human DTAG study summary by adaptive question-selection policy.",
        "Only participants who completed 20 adaptive questions are included.",
        "Completion time is wall-clock time from session creation to finalization,",
        "including baseline questions, adaptive questions, and attention checks.",
        "Baseline signs refer to the LSM-derived ideology coordinate before",
        "adaptive questioning.}",
        "\\label{tab:humanstudy-participants}",
        "\\small",
        "\\setlength{\\tabcolsep}{11pt}",
        "\\begin{tabular}{lrrrr}",
        "\\toprule",
        "Policy & Completed $n$ & Baseline $I_\\Phi<0$ & Baseline $I_\\Phi>0$ & Mean completion (min) \\\\",
        "\\midrule",
    ]
    for s in stats:
        table.append(f"{s['arm']} & {s['n']} & {s['n_neg']} & {s['n_pos']} & {s['mean_minutes']:.1f} \\\\")
    table += ["\\bottomrule", "\\end{tabular}", "\\end{table*}", ""]
    (args.output_dir / "humanstudy_table.tex").write_text("\n".join(table), encoding="utf-8")
    print("Wrote four trajectory series, four endpoint CI series, an arm summary, and the LaTeX table.")
    for s in stats:
        print(f"{s['arm']}: n={s['n']}; baseline -/+={s['n_neg']}/{s['n_pos']}; "
              f"mean completion={s['mean_minutes']:.1f} min; "
              f"endpoint mean={s['mean_change']:+.5f}, CI [{s['ci_low']:+.5f}, {s['ci_high']:+.5f}]")
    print("Compile from tex/: latexmk -pdf -interaction=nonstopmode -halt-on-error DTAG_main.tex")


if __name__ == "__main__":
    main()
