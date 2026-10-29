#!/usr/bin/env python3
"""CI-marked DTAG human ideology trajectories from private GCS archives.

Merges original and follow-up left and right cohorts by assigned policy.
Each incomplete session contributes only actual answered adaptive steps (no padding).
Uses pointwise participant-resampled bootstrap 95% intervals, shaded only
for Left and combined Right by default (all four means are always plotted).

Run from repo root, with authenticated gcloud, numpy and matplotlib:
  python3 human_study/scripts/plot_human_trajectories.py --output dtag_human_trajectories.png
  python3 human_study/scripts/plot_human_trajectories.py --ci-groups all
  python3 human_study/scripts/plot_human_trajectories.py --ci-groups none

Saves PNG, PDF, stepwise summary CSV, and anonymized participant-step CSV.
Reads private GCS objects only. Does not export free-text or Prolific IDs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BUCKET = "pkcsaas-01-dtag-study-data"
ORIGINAL = "prolific-v3-human-opinions-2026-10"
LEFT_FOLLOWUP = "prolific-v3-left-followup-2026-10"
RIGHT_FOLLOWUP = "prolific-v3-right-followup-2026-10"
GROUPS = ("Left", "Right", "Neutral", "Random")
CI_GROUP_NAMES = {"left": GROUPS[0], "right": GROUPS[1],
                  "neutral": GROUPS[2], "random": GROUPS[3]}
ANSWER_RE = re.compile(r"questions/[a-f0-9]{32}\.json$")


def gcloud(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["gcloud", "storage", *args], text=True, stderr=subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise RuntimeError("gcloud not found; run on an authenticated workstation") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or "gcloud storage command failed").strip()) from exc


def archived_files(bucket: str, study: str) -> dict[str, dict[str, str]]:
    prefix = f"gs://{bucket}/studies/{study}/sessions/"
    objects = defaultdict(dict)
    for uri in gcloud("ls", "--recursive", prefix).splitlines():
        if not uri.startswith(prefix):
            continue
        rest = uri[len(prefix):]
        if "/" not in rest:
            continue
        sid, name = rest.split("/", 1)
        if re.fullmatch(r"[a-f0-9]{32}", sid):
            objects[sid][name] = uri
    return dict(objects)


def json_object(uri: str) -> dict:
    result = json.loads(gcloud("cat", uri))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object in {uri}")
    return result


def finite_number(value):
    return (float(value) if isinstance(value, (int, float))
            and not isinstance(value, bool) and math.isfinite(value) else None)


def trajectory(study: str, sid: str, data: dict) -> dict | None:
    """Use actual archived step indices, never an interpolated trajectory."""
    final = data.get("final")
    if final is not None:
        arm = final.get("policy")
        baseline = finite_number(final.get("baseline_index"))
        questions = final.get("questions") or []
        status = "COMPLETE"
    else:
        assignment = data.get("assignment")
        if assignment is None:
            return None
        arm = assignment.get("policy")
        baseline = finite_number(assignment.get("baseline_index"))
        questions = [q.get("question") for q in data.get("answers", [])]
        status = "PARTIAL"
    if arm not in ("left", "right", "neutral", "random") or baseline is None:
        return None
    if study == RIGHT_FOLLOWUP and arm != "right":
        raise ValueError(f"Unexpected arm in right-only study: {sid} {arm}")
    if study == LEFT_FOLLOWUP and arm != "left":
        raise ValueError(f"Unexpected arm in left-only study: {sid} {arm}")
    values = {0: 0.0}
    for q in questions:
        if not isinstance(q, dict) or q.get("phase") != "intervention":
            continue
        step = q.get("step")
        index_result = q.get("index_result")
        after = (finite_number(index_result.get("index_after"))
                 if isinstance(index_result, dict) else None)
        if isinstance(step, int) and not isinstance(step, bool) and 0 <= step < 20 and after is not None:
            t = step + 1
            if t in values and not math.isclose(values[t], after - baseline, abs_tol=1e-10):
                raise ValueError(f"Conflicting Q{t} in session {sid}")
            values[t] = after - baseline
    maxstep = max(values)
    if any(t not in values for t in range(maxstep + 1)):
        raise ValueError(f"Missing intermediate question in session {sid}: {sorted(values)}")
    if final is not None:
        final_index = finite_number(final.get("final_index"))
        if final_index is not None and maxstep == 20 and not math.isclose(
                values[20], final_index - baseline, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError(f"Final index mismatch in session {sid}")
    return {"study_id": study, "session_id": sid, "status": status,
            "group": "Right" if arm == "right" else arm.title(),
            "baseline_index": baseline, "values": values}


def load_sessions(bucket: str, workers: int = 8) -> list[dict]:
    inputs = []
    for study in (ORIGINAL, LEFT_FOLLOWUP, RIGHT_FOLLOWUP):
        for sid, files in archived_files(bucket, study).items():
            if "final.json" in files:
                need = [("final", files["final.json"])]
            elif "events/assignment.json" in files:
                need = [("assignment", files["events/assignment.json"])]
                need.extend(("answers", uri) for name, uri in files.items() if ANSWER_RE.fullmatch(name))
            else:
                continue  # No baseline index yet
            inputs.append((study, sid, need))
    requests = [(study, sid, kind, uri)
                for study, sid, need in inputs for kind, uri in need]
    data = defaultdict(lambda: {"answers": []})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(json_object, uri): (study, sid, kind, uri)
                   for study, sid, kind, uri in requests}
        for task in as_completed(pending):
            study, sid, kind, uri = pending[task]
            try:
                obj = task.result()
            except Exception as exc:
                raise RuntimeError(f"Cannot read {uri}: {exc}") from exc
            if kind == "answers":
                data[(study, sid)]["answers"].append(obj)
            else:
                data[(study, sid)][kind] = obj
    sessions = []
    for study, sid, _ in inputs:
        item = trajectory(study, sid, data[(study, sid)])
        if item is not None:
            sessions.append(item)
    return sessions


def summarize(sessions: list[dict], boots: int = 5000, seed: int = 20261027,
              complete_only: bool = False) -> list[dict]:
    import numpy as np
    rng = np.random.default_rng(seed)
    out = []
    for group in GROUPS:
        items = [s for s in sessions if s["group"] == group
                 and (not complete_only or (s["status"] == "COMPLETE" and 20 in s["values"]))]
        if not items:
            raise ValueError(f"No sessions in group {group}")
        values = np.full((len(items), 21), np.nan)
        for i, item in enumerate(items):
            for step, delta in item["values"].items():
                values[i, step] = delta
        sampled = rng.integers(0, len(items), size=(boots, len(items)))
        mean, low, high, counts = [], [], [], []
        for t in range(21):
            observed = values[:, t]
            counts.append(int(np.isfinite(observed).sum()))
            if not counts[-1]:
                mean.append(float("nan"))
                low.append(float("nan"))
                high.append(float("nan"))
                continue
            mean.append(float(np.nanmean(observed)))
            draws = observed[sampled]  # same resampled participants across all steps
            den = np.isfinite(draws).sum(axis=1)
            bs = np.nansum(draws, axis=1)[den > 0] / den[den > 0]
            low.append(float(np.percentile(bs, 2.5)))
            high.append(float(np.percentile(bs, 97.5)))
        out.append({"group": group, "n_sessions": len(items), "mean": mean,
                    "low": low, "high": high, "counts": counts})
    return out


def parse_ci_groups(value: str) -> frozenset[str]:
    """Parse 'left,right' (default), 'all', 'none', or another arm subset."""
    value = value.strip().lower()
    if value == "all":
        return frozenset(GROUPS)
    if value == "none":
        return frozenset()
    names = [part.strip() for part in value.split(",")]
    if not names or any(name not in CI_GROUP_NAMES for name in names):
        raise argparse.ArgumentTypeError(
            "CI groups must be comma-separated left,right,neutral,random; or all/none")
    return frozenset(CI_GROUP_NAMES[name] for name in names)


def write_outputs(sessions: list[dict], series: list[dict], output: Path,
                  ci_groups: frozenset[str] = frozenset(GROUPS[:2])) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    output.parent.mkdir(parents=True, exist_ok=True)
    xs = np.arange(21)
    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    for item in series:
        label = f'{item["group"]} (n={item["counts"][0]} → {item["counts"][20]})'
        line, = ax.plot(xs, item["mean"], linewidth=2, label=label)
        if item["group"] in ci_groups:
            ax.fill_between(xs, item["low"], item["high"],
                            color=line.get_color(), alpha=0.15, linewidth=0)
    ax.axhline(0, color="0.4", linewidth=0.8, linestyle="--")
    ax.set(xlim=(0, 20), xlabel="Adaptive question number",
           ylabel="Inferred ideology change from baseline",
           title="DTAG human participants: mean observed ideology trajectories")
    ax.set_xticks(range(0, 21, 2))
    ax.legend(loc="best", frameon=False, fontsize=9,
              title="Participants at baseline → question 20")
    ax.grid(axis="y", color="0.85", linewidth=0.5)
    fig.savefig(output, dpi=200, bbox_inches="tight")
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)

    with output.with_name(output.stem + "_summary.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["group", "question", "n_observed", "mean_delta",
                         "bootstrap_ci95_low", "bootstrap_ci95_high"])
        for item in series:
            for t in range(21):
                writer.writerow([item["group"], t, item["counts"][t], item["mean"][t],
                                 item["low"][t], item["high"][t]])

    with output.with_name(output.stem + "_individual.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["study_id", "session_id", "group", "status",
                         "baseline_index", "question", "delta"])
        for item in sessions:
            for step, delta in sorted(item["values"].items()):
                writer.writerow([item["study_id"], item["session_id"], item["group"],
                                 item["status"], item["baseline_index"], step, delta])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--output", type=Path, default=Path("dtag_human_trajectories.png"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--ci-groups", type=parse_ci_groups,
                        default=parse_ci_groups("left,right"), metavar="ARMS",
                        help="Arms with shaded 95%% CI: left,right (default), all, none, "
                             "or any comma-separated subset")
    parser.add_argument("--complete-only", action="store_true",
                        help="Use only completed 20-question sessions")
    args = parser.parse_args()
    if not 1 <= args.workers <= 32 or args.bootstrap < 100:
        parser.error("workers must be 1..32 and bootstrap >= 100")
    sessions = load_sessions(args.bucket, workers=args.workers)
    series = summarize(sessions, boots=args.bootstrap, complete_only=args.complete_only)
    write_outputs(sessions, series, args.output, ci_groups=args.ci_groups)
    print(f"Saved: {args.output}, {args.output.with_suffix('.pdf')}, "
          f"{args.output.stem}_summary.csv, {args.output.stem}_individual.csv")
    for item in series:
        print(f'{item["group"]}: n={item["counts"][0]} → {item["counts"][20]}, '
              f'mean Δ20={item["mean"][20]:+.5f}; '
              f'95% bootstrap CI [{item["low"][20]:+.5f}, {item["high"][20]:+.5f}]')
    shaded = ", ".join(group for group in GROUPS if group in args.ci_groups) or "none"
    print(f"95% pointwise participant-bootstrap bands shown for: {shaded}.")
    print("All arm means and summary CSV intervals retained; partial sessions contribute observed steps only.")


if __name__ == "__main__":
    main()
