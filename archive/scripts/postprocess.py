#!/usr/bin/env python3
"""
Postprocess DTAG batch outputs to test regression-to-mean/center and identify divergent movements.

Designed for the output layout produced by run_dtag_experiment_grid.py / run_dtag_experiment_grid_iloc.py:

  <batch_out>/runs_index.csv
  <batch_out>/runs/.../*.ideology.csv
  <batch_out>/runs/.../*.questions.csv
  <batch_out>/runs/.../*.meta.json

Core outputs:
  postprocess/ideology_long.csv
  postprocess/run_level.csv
  postprocess/condition_summary.csv
  postprocess/topic_summary.csv
  postprocess/regression_to_mean_flags.csv
  postprocess/divergence_flags.csv
  postprocess/order_sensitivity.csv
  postprocess/cross_persona_divergence.csv
  postprocess/postprocess_report.md

Interpretation:
  By default, "mean" means the ideological center, i.e. center = 0 on the ideology index.
  You can change this with --center_mode.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


def mkdir(p: str | Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_read_csv(path: str | Path, **kwargs) -> pd.DataFrame:
    try:
        return pd.read_csv(path, **kwargs)
    except Exception as e:
        raise RuntimeError(f"Failed to read CSV: {path}: {e}")


def find_newest(run_dir: str | Path, pattern: str) -> str:
    rd = Path(run_dir)
    if not rd.exists():
        return ""
    files = sorted(rd.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""




def resolve_batch_out_and_index(batch_arg: str | Path) -> Tuple[Path, Optional[Path]]:
    """Accept either a batch output directory or a direct path to runs_index.csv."""
    p = Path(batch_arg)
    if p.is_file() and p.name == "runs_index.csv":
        return p.parent, p
    if p.is_file() and p.suffix.lower() == ".csv":
        # Be permissive: a CSV file may be an index-like input.
        return p.parent, p
    return p, (p / "runs_index.csv")


def discover_artifact_in_run_dir(run_dir: str | Path, pattern: str) -> str:
    rd = Path(run_dir)
    if not rd.exists():
        return ""
    files = sorted(rd.glob(pattern), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return str(files[0]) if files else ""


def rebuild_runs_index_from_planned(batch_out: Path) -> pd.DataFrame:
    """
    Reconstruct a runs_index-like table when runs_index.csv was not written yet.
    This happens when the launcher was interrupted or exited before merging job results.
    """
    planned_path = batch_out / "jobs_planned.csv"
    if not planned_path.exists():
        raise FileNotFoundError(f"Neither runs_index.csv nor jobs_planned.csv found under {batch_out}")
    planned = pd.read_csv(planned_path, dtype=str).fillna("")
    rows = []
    for _, r in planned.iterrows():
        row = dict(r)
        run_dir = row.get("run_dir", "")
        stdout_path = row.get("stdout_path", "")
        meta = discover_artifact_in_run_dir(run_dir, "*.meta.json")
        ideol = discover_artifact_in_run_dir(run_dir, "*.ideology.csv")
        questions = discover_artifact_in_run_dir(run_dir, "*.questions.csv")
        final_state = discover_artifact_in_run_dir(run_dir, "*.final_state.json")
        row["meta_json"] = meta
        row["ideology_csv"] = ideol
        row["questions_csv"] = questions
        row["final_state_json"] = final_state
        if ideol and Path(ideol).exists():
            row["status"] = "ok"
            row["returncode"] = row.get("returncode", "0") or "0"
        elif stdout_path and Path(stdout_path).exists():
            txt = ""
            try:
                txt = Path(stdout_path).read_text(errors="ignore")[-4000:]
            except Exception:
                pass
            row["status"] = "failed_or_incomplete"
            if "Traceback" in txt or "ValueError" in txt or "ERROR" in txt:
                row["error"] = txt.replace("\n", " ")[-1000:]
        else:
            row["status"] = "not_started_or_missing"
        rows.append(row)
    return pd.DataFrame(rows)


def parse_qset_type(qset: str) -> str:
    q = str(qset).lower()
    if q.startswith("increase") or "increased" in q or "score_increased" in q:
        return "increase_candidate"
    if q.startswith("reduce") or "fell" in q or "score_fell" in q:
        return "reduce_candidate"
    return "unlabeled"


def sign_label(x: float, eps: float) -> str:
    if not np.isfinite(x) or abs(x) <= eps:
        return "zero"
    return "positive" if x > 0 else "negative"


def movement_label(distance_change: float, eps: float) -> str:
    if not np.isfinite(distance_change) or abs(distance_change) <= eps:
        return "no_change"
    return "toward_center" if distance_change < 0 else "away_from_center"


def signed_delta_label(delta: float, eps: float) -> str:
    if not np.isfinite(delta) or abs(delta) <= eps:
        return "no_change"
    return "rightward" if delta > 0 else "leftward"


def exact_sign_test_p(n_pos: int, n_neg: int) -> float:
    """Two-sided exact binomial sign test over nonzero signs, null p=0.5."""
    n = int(n_pos + n_neg)
    if n <= 0:
        return float("nan")
    k = min(n_pos, n_neg)
    # two-sided p = 2 * P[X <= min(k, n-k)] capped at 1
    prob = 0.0
    for i in range(k + 1):
        prob += math.comb(n, i) * (0.5 ** n)
    return min(1.0, 2.0 * prob)


def bootstrap_ci_mean(x: Iterable[float], n_boot: int = 2000, seed: int = 1, alpha: float = 0.05) -> Tuple[float, float]:
    arr = np.array([v for v in x if np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"))
    if arr.size == 1 or n_boot <= 0:
        return (float(arr.mean()), float(arr.mean()))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(int(n_boot), arr.size))
    vals = arr[idx].mean(axis=1)
    lo = float(np.quantile(vals, alpha / 2.0))
    hi = float(np.quantile(vals, 1.0 - alpha / 2.0))
    return lo, hi


def slope_from_series(df: pd.DataFrame) -> float:
    d = df[["step", "ideology_index"]].dropna().copy()
    if d.shape[0] < 2:
        return float("nan")
    x = d["step"].astype(float).to_numpy()
    y = d["ideology_index"].astype(float).to_numpy()
    if np.allclose(x, x[0]):
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def load_run_ideology(row: pd.Series, batch_out: Path) -> Optional[pd.DataFrame]:
    ideol_path = str(row.get("ideology_csv", "") or "")
    if not ideol_path:
        ideol_path = find_newest(row.get("run_dir", ""), "*.ideology.csv")
    if not ideol_path:
        return None
    p = Path(ideol_path)
    if not p.is_absolute():
        p = (batch_out / p).resolve()
    if not p.exists():
        # If runs_index stores a path relative to current working dir, try as-is.
        p2 = Path(ideol_path)
        if p2.exists():
            p = p2
        else:
            return None
    try:
        df = pd.read_csv(p)
    except Exception:
        return None
    if "step" not in df.columns or "ideology_index" not in df.columns:
        return None
    df = df[["step", "ideology_index"]].copy()
    df["step"] = pd.to_numeric(df["step"], errors="coerce")
    df["ideology_index"] = pd.to_numeric(df["ideology_index"], errors="coerce")
    df = df.dropna(subset=["step", "ideology_index"]).sort_values("step")
    if df.empty:
        return None
    return df


def choose_centers(run_level: pd.DataFrame, mode: str, center_value: float) -> pd.Series:
    if mode == "zero":
        return pd.Series(center_value, index=run_level.index, dtype=float)
    if mode == "global_initial":
        c = float(run_level["initial"].mean())
        return pd.Series(c, index=run_level.index, dtype=float)
    if mode == "persona_initial":
        centers = run_level.groupby("persona_id")["initial"].transform("mean")
        return centers.astype(float)
    if mode == "question_set_initial":
        centers = run_level.groupby("question_set")["initial"].transform("mean")
        return centers.astype(float)
    if mode == "persona_question_initial":
        centers = run_level.groupby(["persona_id", "question_set"])["initial"].transform("mean")
        return centers.astype(float)
    raise ValueError(f"Unknown center_mode: {mode}")


def summarize_condition(group: pd.DataFrame, eps: float, effect_threshold: float, n_boot: int, seed: int) -> Dict[str, object]:
    x = group.copy()
    n = int(x.shape[0])
    n_toward = int((x["movement"] == "toward_center").sum())
    n_away = int((x["movement"] == "away_from_center").sum())
    n_no = int((x["movement"] == "no_change").sum())
    n_left = int((x["signed_delta_direction"] == "leftward").sum())
    n_right = int((x["signed_delta_direction"] == "rightward").sum())

    mean_distance_change = float(x["distance_change"].mean()) if n else float("nan")
    mean_delta = float(x["delta"].mean()) if n else float("nan")
    mean_initial = float(x["initial"].mean()) if n else float("nan")
    mean_final = float(x["final"].mean()) if n else float("nan")
    mean_abs_initial = float(x["initial_distance"].mean()) if n else float("nan")
    mean_abs_final = float(x["final_distance"].mean()) if n else float("nan")
    sd_final = float(x["final"].std(ddof=1)) if n > 1 else 0.0
    sd_delta = float(x["delta"].std(ddof=1)) if n > 1 else 0.0
    sd_distance_change = float(x["distance_change"].std(ddof=1)) if n > 1 else 0.0

    dci_lo, dci_hi = bootstrap_ci_mean(x["distance_change"], n_boot=n_boot, seed=seed)
    del_ci_lo, del_ci_hi = bootstrap_ci_mean(x["delta"], n_boot=n_boot, seed=seed + 17)
    sign_p = exact_sign_test_p(n_toward, n_away)

    frac_toward = n_toward / n if n else float("nan")
    frac_away = n_away / n if n else float("nan")
    frac_left = n_left / n if n else float("nan")
    frac_right = n_right / n if n else float("nan")

    if n == 0:
        flag = "empty"
    elif frac_toward >= 0.75 and mean_distance_change < -effect_threshold:
        flag = "consistent_toward_center"
    elif frac_away >= 0.75 and mean_distance_change > effect_threshold:
        flag = "consistent_away_from_center"
    elif frac_toward >= 0.25 and frac_away >= 0.25:
        flag = "mixed_replicate_directions"
    elif abs(mean_distance_change) <= effect_threshold:
        flag = "weak_or_stable_distance_change"
    elif mean_distance_change < 0:
        flag = "mostly_toward_center"
    else:
        flag = "mostly_away_from_center"

    if frac_left >= 0.75 and mean_delta < -effect_threshold:
        signed_flag = "consistent_leftward"
    elif frac_right >= 0.75 and mean_delta > effect_threshold:
        signed_flag = "consistent_rightward"
    elif frac_left >= 0.25 and frac_right >= 0.25:
        signed_flag = "mixed_left_right"
    else:
        signed_flag = "weak_or_stable_signed_change"

    return {
        "n_runs": n,
        "mean_initial": mean_initial,
        "mean_final": mean_final,
        "mean_delta": mean_delta,
        "delta_ci95_lo": del_ci_lo,
        "delta_ci95_hi": del_ci_hi,
        "mean_initial_distance": mean_abs_initial,
        "mean_final_distance": mean_abs_final,
        "mean_distance_change": mean_distance_change,
        "distance_change_ci95_lo": dci_lo,
        "distance_change_ci95_hi": dci_hi,
        "sd_final": sd_final,
        "sd_delta": sd_delta,
        "sd_distance_change": sd_distance_change,
        "n_toward_center": n_toward,
        "n_away_from_center": n_away,
        "n_no_change": n_no,
        "frac_toward_center": frac_toward,
        "frac_away_from_center": frac_away,
        "n_leftward": n_left,
        "n_rightward": n_right,
        "frac_leftward": frac_left,
        "frac_rightward": frac_right,
        "sign_test_p_toward_vs_away": sign_p,
        "regression_flag": flag,
        "signed_delta_flag": signed_flag,
    }


def make_condition_summary(run_level: pd.DataFrame, group_cols: List[str], eps: float, effect_threshold: float, n_boot: int, seed: int) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    for keys, g in run_level.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {c: k for c, k in zip(group_cols, keys)}
        row.update(summarize_condition(g, eps=eps, effect_threshold=effect_threshold, n_boot=n_boot, seed=seed + len(rows)))
        rows.append(row)
    return pd.DataFrame(rows)


def make_step_summary(ideology_long: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["persona_id", "question_set", "variant", "step"]
    rows = []
    for keys, g in ideology_long.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {c: k for c, k in zip(group_cols, keys)}
        vals = pd.to_numeric(g["ideology_index"], errors="coerce").dropna()
        row.update({
            "n_runs": int(vals.shape[0]),
            "mean_ideology": float(vals.mean()) if len(vals) else float("nan"),
            "sd_ideology": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0,
            "median_ideology": float(vals.median()) if len(vals) else float("nan"),
            "q25_ideology": float(vals.quantile(0.25)) if len(vals) else float("nan"),
            "q75_ideology": float(vals.quantile(0.75)) if len(vals) else float("nan"),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def make_order_sensitivity(condition_summary: pd.DataFrame, effect_threshold: float) -> pd.DataFrame:
    rows = []
    needed = {"persona_id", "question_set", "variant", "mean_final", "mean_delta", "mean_distance_change", "regression_flag", "signed_delta_flag"}
    if not needed.issubset(condition_summary.columns):
        return pd.DataFrame()
    for keys, g in condition_summary.groupby(["persona_id", "question_set"], dropna=False):
        if g["variant"].nunique() < 2:
            continue
        final_range = float(g["mean_final"].max() - g["mean_final"].min())
        delta_range = float(g["mean_delta"].max() - g["mean_delta"].min())
        dist_change_range = float(g["mean_distance_change"].max() - g["mean_distance_change"].min())
        signed_signs = set(sign_label(v, effect_threshold) for v in g["mean_delta"].tolist()) - {"zero"}
        dist_signs = set(sign_label(v, effect_threshold) for v in g["mean_distance_change"].tolist()) - {"zero"}
        order_flag = "order_stable"
        if len(signed_signs) > 1 or len(dist_signs) > 1:
            order_flag = "order_changes_direction"
        elif max(abs(delta_range), abs(dist_change_range), abs(final_range)) >= effect_threshold:
            order_flag = "order_changes_magnitude"
        rows.append({
            "persona_id": keys[0],
            "question_set": keys[1],
            "n_variants": int(g["variant"].nunique()),
            "variants": ";".join(sorted(map(str, g["variant"].unique()))),
            "mean_final_range": final_range,
            "mean_delta_range": delta_range,
            "mean_distance_change_range": dist_change_range,
            "signed_delta_signs": ";".join(sorted(signed_signs)) if signed_signs else "zero_or_weak",
            "distance_change_signs": ";".join(sorted(dist_signs)) if dist_signs else "zero_or_weak",
            "order_sensitivity_flag": order_flag,
        })
    return pd.DataFrame(rows)


def make_cross_persona_divergence(condition_summary: pd.DataFrame, effect_threshold: float) -> pd.DataFrame:
    rows = []
    needed = {"persona_id", "question_set", "variant", "mean_delta", "mean_distance_change", "regression_flag", "signed_delta_flag"}
    if not needed.issubset(condition_summary.columns):
        return pd.DataFrame()
    for keys, g in condition_summary.groupby(["question_set", "variant"], dropna=False):
        if g["persona_id"].nunique() < 2:
            continue
        records = list(g.to_dict("records"))
        for a, b in combinations(records, 2):
            delta_opposite = sign_label(a["mean_delta"], effect_threshold) != sign_label(b["mean_delta"], effect_threshold)
            delta_strong = abs(float(a["mean_delta"])) >= effect_threshold and abs(float(b["mean_delta"])) >= effect_threshold
            dist_opposite = sign_label(a["mean_distance_change"], effect_threshold) != sign_label(b["mean_distance_change"], effect_threshold)
            dist_strong = abs(float(a["mean_distance_change"])) >= effect_threshold and abs(float(b["mean_distance_change"])) >= effect_threshold
            flag = "not_divergent"
            if delta_opposite and delta_strong and dist_opposite and dist_strong:
                flag = "opposite_signed_and_center_movement"
            elif delta_opposite and delta_strong:
                flag = "opposite_signed_delta"
            elif dist_opposite and dist_strong:
                flag = "opposite_center_movement"
            rows.append({
                "question_set": keys[0],
                "variant": keys[1],
                "persona_a": a["persona_id"],
                "persona_b": b["persona_id"],
                "mean_delta_a": a["mean_delta"],
                "mean_delta_b": b["mean_delta"],
                "mean_distance_change_a": a["mean_distance_change"],
                "mean_distance_change_b": b["mean_distance_change"],
                "regression_flag_a": a["regression_flag"],
                "regression_flag_b": b["regression_flag"],
                "signed_delta_flag_a": a["signed_delta_flag"],
                "signed_delta_flag_b": b["signed_delta_flag"],
                "cross_persona_flag": flag,
            })
    return pd.DataFrame(rows)


def write_report(
    out_path: Path,
    args: argparse.Namespace,
    runs_index: pd.DataFrame,
    run_level: pd.DataFrame,
    condition_summary: pd.DataFrame,
    order_sensitivity: pd.DataFrame,
    cross_persona: pd.DataFrame,
) -> None:
    ok_runs = int((runs_index.get("status", pd.Series(dtype=str)) == "ok").sum()) if "status" in runs_index.columns else len(runs_index)
    analyzed = int(run_level.shape[0])

    lines: List[str] = []
    lines.append("# DTAG postprocessing report")
    lines.append("")
    lines.append(f"Batch output: `{args.batch_out}`")
    lines.append(f"Center mode: `{args.center_mode}`; center value parameter: `{args.center}`")
    lines.append(f"Effect threshold: `{args.effect_threshold}`; epsilon: `{args.epsilon}`")
    lines.append("")
    lines.append(f"Runs in index: {len(runs_index)}")
    lines.append(f"Runs marked OK: {ok_runs}")
    lines.append(f"Runs analyzed with ideology CSV: {analyzed}")
    lines.append("")

    if condition_summary.empty:
        lines.append("No condition summaries were produced.")
    else:
        lines.append("## Regression-to-center flags")
        counts = condition_summary["regression_flag"].value_counts(dropna=False)
        for k, v in counts.items():
            lines.append(f"- {k}: {int(v)} conditions")
        lines.append("")
        top_away = condition_summary.sort_values("mean_distance_change", ascending=False).head(10)
        top_toward = condition_summary.sort_values("mean_distance_change", ascending=True).head(10)
        lines.append("## Strongest away-from-center conditions")
        for _, r in top_away.iterrows():
            lines.append(
                f"- {r.get('persona_id')} | {r.get('question_set')} | {r.get('variant')}: "
                f"mean_distance_change={float(r.get('mean_distance_change', np.nan)):.6f}, "
                f"mean_delta={float(r.get('mean_delta', np.nan)):.6f}, flag={r.get('regression_flag')}"
            )
        lines.append("")
        lines.append("## Strongest toward-center conditions")
        for _, r in top_toward.iterrows():
            lines.append(
                f"- {r.get('persona_id')} | {r.get('question_set')} | {r.get('variant')}: "
                f"mean_distance_change={float(r.get('mean_distance_change', np.nan)):.6f}, "
                f"mean_delta={float(r.get('mean_delta', np.nan)):.6f}, flag={r.get('regression_flag')}"
            )
        lines.append("")

    if not order_sensitivity.empty:
        sens = order_sensitivity[order_sensitivity["order_sensitivity_flag"] != "order_stable"]
        lines.append("## Order sensitivity")
        lines.append(f"Order-sensitive persona/question-set pairs: {sens.shape[0]} of {order_sensitivity.shape[0]}")
        for _, r in sens.head(20).iterrows():
            lines.append(
                f"- {r.get('persona_id')} | {r.get('question_set')}: "
                f"{r.get('order_sensitivity_flag')}, "
                f"delta_range={float(r.get('mean_delta_range', np.nan)):.6f}, "
                f"distance_change_range={float(r.get('mean_distance_change_range', np.nan)):.6f}"
            )
        lines.append("")

    if not cross_persona.empty:
        div = cross_persona[cross_persona["cross_persona_flag"] != "not_divergent"]
        lines.append("## Cross-persona divergence")
        lines.append(f"Divergent cross-persona comparisons: {div.shape[0]} of {cross_persona.shape[0]}")
        for _, r in div.head(20).iterrows():
            lines.append(
                f"- {r.get('question_set')} | {r.get('variant')} | {r.get('persona_a')} vs {r.get('persona_b')}: "
                f"{r.get('cross_persona_flag')}; "
                f"delta=({float(r.get('mean_delta_a', np.nan)):.6f}, {float(r.get('mean_delta_b', np.nan)):.6f}); "
                f"distance_change=({float(r.get('mean_distance_change_a', np.nan)):.6f}, {float(r.get('mean_distance_change_b', np.nan)):.6f})"
            )
        lines.append("")

    lines.append("## Interpretation notes")
    lines.append("")
    lines.append("`mean_distance_change < 0` means movement toward the chosen center. With the default settings, this is movement toward ideology index 0. `mean_distance_change > 0` means movement away from that center. This is a test of centering/regression-to-center, not proof of the empirical population mean unless the chosen center is set accordingly.")
    lines.append("")
    lines.append("Evidence against trivial regression-to-mean is strongest where conditions show consistent away-from-center movement, mixed replicate directions, order sensitivity, or cross-persona opposite movement for the same question set.")
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def make_basic_plots(post_dir: Path, condition_summary: pd.DataFrame, run_level: pd.DataFrame) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"WARNING: matplotlib unavailable; skipping plots: {e}", file=sys.stderr)
        return

    plot_dir = mkdir(post_dir / "plots")

    if not condition_summary.empty:
        df = condition_summary.sort_values("mean_distance_change").copy()
        labels = (df["persona_id"].astype(str) + " | " + df["question_set"].astype(str) + " | " + df["variant"].astype(str)).tolist()
        # Cap plotted rows to avoid unreadable giant figures.
        max_rows = min(80, len(df))
        if len(df) > max_rows:
            # Keep strongest toward and away.
            half = max_rows // 2
            df = pd.concat([df.head(half), df.tail(max_rows - half)], ignore_index=True)
            labels = (df["persona_id"].astype(str) + " | " + df["question_set"].astype(str) + " | " + df["variant"].astype(str)).tolist()
        y = np.arange(len(df))
        fig_h = max(6, 0.20 * len(df) + 2)
        plt.figure(figsize=(12, fig_h))
        plt.barh(y, df["mean_distance_change"].astype(float).to_numpy())
        plt.axvline(0, linewidth=1)
        plt.yticks(y, labels, fontsize=7)
        plt.xlabel("Mean distance change: final distance to center minus initial distance")
        plt.title("DTAG regression-to-center diagnostic by condition")
        plt.tight_layout()
        plt.savefig(plot_dir / "condition_distance_change_bar.png", dpi=180)
        plt.close()

    if not run_level.empty:
        plt.figure(figsize=(8, 6))
        plt.scatter(run_level["initial_distance"], run_level["final_distance"], alpha=0.7)
        mn = float(min(run_level["initial_distance"].min(), run_level["final_distance"].min()))
        mx = float(max(run_level["initial_distance"].max(), run_level["final_distance"].max()))
        plt.plot([mn, mx], [mn, mx], linewidth=1)
        plt.xlabel("Initial distance to center")
        plt.ylabel("Final distance to center")
        plt.title("Run-level regression-to-center check")
        plt.tight_layout()
        plt.savefig(plot_dir / "initial_vs_final_distance.png", dpi=180)
        plt.close()



# -----------------------------
# Integrated confidence and quadrant plotting
# -----------------------------

def safe_name(s: object) -> str:
    s = str(s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "item"


def prettify_qset(q: object) -> str:
    s = str(q)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normal_z_for_ci(ci: float) -> float:
    table = {
        0.80: 1.2815515655446004,
        0.90: 1.6448536269514722,
        0.95: 1.959963984540054,
        0.98: 2.3263478740408408,
        0.99: 2.5758293035489004,
    }
    closest = min(table.keys(), key=lambda k: abs(k - float(ci)))
    if abs(closest - float(ci)) < 1e-9:
        return table[closest]
    print(f"WARNING: unsupported CI {ci}; using 0.95", file=sys.stderr)
    return table[0.95]


def normal_ci_mean(vals: Iterable[object], ci: float = 0.95) -> Tuple[float, float, float, int, float]:
    arr = pd.to_numeric(pd.Series(list(vals)), errors="coerce").dropna().to_numpy(dtype=float)
    n = len(arr)
    if n == 0:
        return (float("nan"), float("nan"), float("nan"), 0, float("nan"))
    m = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    half = normal_z_for_ci(ci) * sd / math.sqrt(n) if n > 1 else 0.0
    return (m, m - half, m + half, n, sd)


def grouped_normal_ci(df: pd.DataFrame, group_cols: List[str], value_col: str, ci: float) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(group_cols, sort=True, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        m, lo, hi, n, sd = normal_ci_mean(g[value_col], ci=ci)
        row = {c: v for c, v in zip(group_cols, key)}
        row.update({"mean": m, "lower": lo, "upper": hi, "n": n, "sd": sd})
        rows.append(row)
    return pd.DataFrame(rows)


def set_plot_theme(dark: bool, transparent: bool) -> None:
    import matplotlib.pyplot as plt
    if dark:
        fg = "#f2f2f2"
        grid = "#8a8a8a"
        face = "#111111" if not transparent else "none"
        axes_face = "#111111" if not transparent else "none"
    else:
        fg = "#111111"
        grid = "#9a9a9a"
        face = "white" if not transparent else "none"
        axes_face = "white" if not transparent else "none"
    plt.rcParams.update({
        "figure.facecolor": face,
        "axes.facecolor": axes_face,
        "savefig.facecolor": face,
        "text.color": fg,
        "axes.labelcolor": fg,
        "axes.edgecolor": fg,
        "xtick.color": fg,
        "ytick.color": fg,
        "axes.titlecolor": fg,
        "legend.labelcolor": fg,
        "grid.color": grid,
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
    })


def save_plot_figure(fig, path_base: Path, dpi: int, transparent: bool, pdf: bool) -> None:
    path_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_base.with_suffix(".png"), dpi=dpi, transparent=transparent, bbox_inches="tight")
    if pdf:
        fig.savefig(path_base.with_suffix(".pdf"), transparent=transparent, bbox_inches="tight")


def load_label_map(label_map_csv: str = "") -> Dict[str, str]:
    if not label_map_csv:
        return {}
    p = Path(label_map_csv)
    if not p.exists():
        print(f"WARNING: label map not found: {label_map_csv}", file=sys.stderr)
        return {}
    try:
        df = pd.read_csv(p, dtype=str).fillna("")
    except Exception as e:
        print(f"WARNING: failed to read label map {p}: {e}", file=sys.stderr)
        return {}
    cols = {c.lower(): c for c in df.columns}
    qcol = cols.get("question_set") or cols.get("filename") or cols.get("file") or df.columns[0]
    lcol = cols.get("interpretive_name") or cols.get("label") or cols.get("name")
    if lcol is None:
        if len(df.columns) >= 2:
            lcol = df.columns[1]
        else:
            return {}
    out: Dict[str, str] = {}
    for _, r in df.iterrows():
        q = str(r[qcol]).strip()
        lab = str(r[lcol]).strip()
        if q.endswith(".csv"):
            q = q[:-4]
        if q and lab:
            out[q] = lab
    return out


def default_question_label(qset: object, label_map: Optional[Dict[str, str]] = None) -> str:
    q = str(qset)
    if label_map and q in label_map:
        return label_map[q]
    if label_map and q + ".csv" in label_map:
        return label_map[q + ".csv"]
    # Filename-based fallback. Intended only if no explicit label map is supplied.
    s = q
    s = s.replace("increase_set_", "inc ")
    s = s.replace("reduce_set_", "red ")
    s = s.replace("questions_score_", "score ")
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ensure_plot_long_columns(ideology_long: pd.DataFrame) -> pd.DataFrame:
    df = ideology_long.copy()
    if "persona_short" not in df.columns:
        extracted = df["persona_id"].astype(str).str.extract(r"^(WF|CM|[A-Z]{2,4})", expand=False)
        df["persona_short"] = extracted.fillna(df["persona_id"].astype(str))
    df["step"] = pd.to_numeric(df["step"], errors="coerce")
    df["ideology_index"] = pd.to_numeric(df["ideology_index"], errors="coerce")
    if "center" not in df.columns:
        df["center"] = 0.0
    df["center"] = pd.to_numeric(df["center"], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["step", "ideology_index"])
    df["step"] = df["step"].astype(int)
    return df


def make_confidence_trajectory_plots(
    ideology_long: pd.DataFrame,
    plot_dir: Path,
    variant: str = "forward",
    ci: float = 0.95,
    dpi: int = 220,
    dark: bool = False,
    transparent: bool = False,
    pdf: bool = False,
    show_replicates: bool = False,
    band_alpha: float = 0.20,
    grid_alpha: float = 0.25,
    traj_width: float = 7.5,
    traj_height: float = 4.5,
    label_map: Optional[Dict[str, str]] = None,
) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    set_plot_theme(dark=dark, transparent=transparent)
    df = ensure_plot_long_columns(ideology_long)
    if variant.lower() != "all":
        df = df[df["variant"].astype(str) == variant].copy()
    if df.empty:
        return 0
    out = mkdir(plot_dir / f"trajectories_{safe_name(variant)}")
    nplots = 0
    for (persona, qset), g in df.groupby(["persona_short", "question_set"], sort=True, dropna=False):
        s = grouped_normal_ci(g, ["step"], "ideology_index", ci=ci).sort_values("step")
        if s.empty:
            continue
        x = s["step"].to_numpy(dtype=float)
        y = s["mean"].to_numpy(dtype=float)
        lo = s["lower"].to_numpy(dtype=float)
        hi = s["upper"].to_numpy(dtype=float)
        center_val = float(pd.to_numeric(g["center"], errors="coerce").dropna().iloc[0]) if "center" in g.columns and not g["center"].dropna().empty else 0.0
        fig, ax = plt.subplots(figsize=(traj_width, traj_height))
        if show_replicates and "job_id" in g.columns:
            for _, rg in g.groupby("job_id"):
                rg = rg.sort_values("step")
                ax.plot(rg["step"], rg["ideology_index"], linewidth=0.8, alpha=0.25)
        ax.plot(x, y, marker="o", linewidth=2, label="Mean ideology index")
        ax.fill_between(x, lo, hi, alpha=band_alpha, label=f"{int(ci*100)}% CI")
        ax.axhline(center_val, linestyle="--", linewidth=1)
        ax.set_title(f"{persona}: {default_question_label(qset, label_map)}")
        ax.set_xlabel("Question step")
        ax.set_ylabel("Ideology index")
        ax.legend(frameon=False)
        ax.grid(True, alpha=grid_alpha)
        fig.tight_layout()
        save_plot_figure(fig, out / f"trajectory_{safe_name(persona)}__{safe_name(qset)}__{safe_name(variant)}", dpi=dpi, transparent=transparent, pdf=pdf)
        plt.close(fig)
        nplots += 1
    return nplots


def endpoint_summary_for_plots(run_level: pd.DataFrame, variant: str, ci: float) -> pd.DataFrame:
    df = run_level.copy()
    df["persona_short"] = df["persona_id"].astype(str).str.extract(r"^(WF|CM|[A-Z]{2,4})", expand=False).fillna(df["persona_id"].astype(str))
    if variant.lower() != "all":
        df = df[df["variant"].astype(str) == variant].copy()
    rows = []
    for (persona, qset), g in df.groupby(["persona_short", "question_set"], sort=True, dropna=False):
        row = {"persona": persona, "question_set": qset, "n_runs": int(g["job_id"].nunique())}
        for col in ["initial", "final", "delta", "distance_change"]:
            out_name = "signed_delta" if col == "delta" else col
            m, lo, hi, n, sd = normal_ci_mean(g[col], ci=ci)
            row[f"{out_name}_mean"] = m
            row[f"{out_name}_lower"] = lo
            row[f"{out_name}_upper"] = hi
            row[f"{out_name}_sd"] = sd
        row["frac_toward_center"] = float((g["movement"] == "toward_center").mean()) if "movement" in g.columns and len(g) else float("nan")
        row["frac_away_from_center"] = float((g["movement"] == "away_from_center").mean()) if "movement" in g.columns and len(g) else float("nan")
        row["signed_direction"] = "rightward" if row["signed_delta_mean"] > 0 else "leftward" if row["signed_delta_mean"] < 0 else "flat"
        row["mean_reversion_signal"] = bool(row["distance_change_mean"] < -0.005)
        row["away_from_center_signal"] = bool(row["distance_change_mean"] > 0.005)
        rows.append(row)
    return pd.DataFrame(rows)


def make_confidence_summary_plots(
    run_level: pd.DataFrame,
    plot_dir: Path,
    variant: str = "forward",
    ci: float = 0.95,
    dpi: int = 220,
    dark: bool = False,
    transparent: bool = False,
    pdf: bool = False,
    grid_alpha: float = 0.25,
    summary_width: float = 11.0,
    summary_height: float = 4.5,
    label_map: Optional[Dict[str, str]] = None,
) -> Tuple[int, pd.DataFrame]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    set_plot_theme(dark=dark, transparent=transparent)
    summary = endpoint_summary_for_plots(run_level, variant=variant, ci=ci)
    out = mkdir(plot_dir / "summary")
    if not summary.empty:
        summary.to_csv(out / f"condition_summary_{safe_name(variant)}.csv", index=False)
    nplots = 0
    for persona, g in summary.groupby("persona", sort=True, dropna=False):
        gg = g.sort_values("signed_delta_mean")
        yloc = np.arange(len(gg))
        y = gg["signed_delta_mean"].to_numpy(dtype=float)
        lo = gg["signed_delta_lower"].to_numpy(dtype=float)
        hi = gg["signed_delta_upper"].to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(summary_width, max(summary_height, 0.35 * len(gg) + 2)))
        ax.errorbar(y, yloc, xerr=[y - lo, hi - y], fmt="o", capsize=3)
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.set_yticks(yloc)
        ax.set_yticklabels([default_question_label(q, label_map) for q in gg["question_set"]])
        ax.set_xlabel("Final minus initial ideology index")
        ax.set_ylabel("Question set")
        ax.set_title(f"{persona}: {variant} signed ideology shift with {int(ci*100)}% CI")
        ax.grid(True, axis="x", alpha=grid_alpha)
        fig.tight_layout()
        save_plot_figure(fig, out / f"summary_signed_delta_{safe_name(persona)}__{safe_name(variant)}", dpi=dpi, transparent=transparent, pdf=pdf)
        plt.close(fig)
        nplots += 1

        gg = g.sort_values("distance_change_mean")
        yloc = np.arange(len(gg))
        y = gg["distance_change_mean"].to_numpy(dtype=float)
        lo = gg["distance_change_lower"].to_numpy(dtype=float)
        hi = gg["distance_change_upper"].to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(summary_width, max(summary_height, 0.35 * len(gg) + 2)))
        ax.errorbar(y, yloc, xerr=[y - lo, hi - y], fmt="o", capsize=3)
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.set_yticks(yloc)
        ax.set_yticklabels([default_question_label(q, label_map) for q in gg["question_set"]])
        ax.set_xlabel("Change in distance to center; negative means toward center")
        ax.set_ylabel("Question set")
        ax.set_title(f"{persona}: {variant} regression-to-mean diagnostic with {int(ci*100)}% CI")
        ax.grid(True, axis="x", alpha=grid_alpha)
        fig.tight_layout()
        save_plot_figure(fig, out / f"summary_distance_change_{safe_name(persona)}__{safe_name(variant)}", dpi=dpi, transparent=transparent, pdf=pdf)
        plt.close(fig)
        nplots += 1
    return nplots, summary


def make_quadrant_summary_plot(
    run_level: pd.DataFrame,
    plot_dir: Path,
    variant: str = "all",
    ci: float = 0.95,
    dpi: int = 220,
    dark: bool = False,
    transparent: bool = False,
    pdf: bool = False,
    label_map: Optional[Dict[str, str]] = None,
    numbered: bool = True,
) -> Tuple[int, pd.DataFrame]:
    """
    One point per question set. X = CM mean final-initial ideology shift.
    Y = WF mean final-initial ideology shift. Error bars are CI across runs.
    If personas are not literally CM/WF, the first two persona_short values are used.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    set_plot_theme(dark=dark, transparent=transparent)
    df = run_level.copy()
    df["persona_short"] = df["persona_id"].astype(str).str.extract(r"^(WF|CM|[A-Z]{2,4})", expand=False).fillna(df["persona_id"].astype(str))
    if variant.lower() != "all":
        df = df[df["variant"].astype(str) == variant].copy()
    if df.empty:
        return 0, pd.DataFrame()
    rows = []
    for (persona, qset), g in df.groupby(["persona_short", "question_set"], sort=True, dropna=False):
        m, lo, hi, n, sd = normal_ci_mean(g["delta"], ci=ci)
        md, dlo, dhi, _, _ = normal_ci_mean(g["distance_change"], ci=ci)
        rows.append({
            "persona": persona,
            "question_set": qset,
            "delta_mean": m,
            "delta_ci_lo": lo,
            "delta_ci_hi": hi,
            "delta_ci_half": max(abs(m - lo), abs(hi - m)) if np.isfinite(m) else float("nan"),
            "distance_change_mean": md,
            "n_runs": n,
        })
    summary = pd.DataFrame(rows)
    if summary.empty:
        return 0, pd.DataFrame()
    personas = list(summary["persona"].dropna().unique())
    if "CM" in personas and "WF" in personas:
        x_persona, y_persona = "CM", "WF"
    elif len(personas) >= 2:
        x_persona, y_persona = personas[0], personas[1]
    else:
        print("WARNING: quadrant plot requires at least two personas", file=sys.stderr)
        return 0, pd.DataFrame()
    wide_delta = summary.pivot(index="question_set", columns="persona", values="delta_mean").reset_index()
    wide_ci = summary.pivot(index="question_set", columns="persona", values="delta_ci_half").reset_index()
    wide_dist = summary.pivot(index="question_set", columns="persona", values="distance_change_mean").reset_index()
    plot_df = wide_delta[["question_set", x_persona, y_persona]].dropna().copy()
    if plot_df.empty:
        return 0, pd.DataFrame()
    plot_df[f"{x_persona}_ci"] = wide_ci.set_index("question_set").reindex(plot_df["question_set"])[x_persona].to_numpy()
    plot_df[f"{y_persona}_ci"] = wide_ci.set_index("question_set").reindex(plot_df["question_set"])[y_persona].to_numpy()
    plot_df[f"{x_persona}_distance_change"] = wide_dist.set_index("question_set").reindex(plot_df["question_set"])[x_persona].to_numpy()
    plot_df[f"{y_persona}_distance_change"] = wide_dist.set_index("question_set").reindex(plot_df["question_set"])[y_persona].to_numpy()
    plot_df["label"] = plot_df["question_set"].apply(lambda q: default_question_label(q, label_map))
    plot_df = plot_df.sort_values("question_set").reset_index(drop=True)
    plot_df["num"] = np.arange(1, len(plot_df) + 1)

    out = mkdir(plot_dir / "quadrant")
    plot_df.to_csv(out / f"quadrant_summary_{safe_name(variant)}.csv", index=False)
    key_df = plot_df[["num", "question_set", "label", x_persona, y_persona, f"{x_persona}_ci", f"{y_persona}_ci", f"{x_persona}_distance_change", f"{y_persona}_distance_change"]].copy()
    key_df.to_csv(out / f"quadrant_numbered_label_key_{safe_name(variant)}.csv", index=False)
    md = ["# Quadrant numbered label key", ""]
    for _, r in key_df.iterrows():
        md.append(f"{int(r['num'])}. **{r['label']}** (`{r['question_set']}`)")
    (out / f"quadrant_numbered_label_key_{safe_name(variant)}.md").write_text("\n".join(md), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(8.5, 7.5) if numbered else (12.5, 9.5))
    ax.errorbar(
        plot_df[x_persona], plot_df[y_persona],
        xerr=plot_df[f"{x_persona}_ci"], yerr=plot_df[f"{y_persona}_ci"],
        fmt="o", capsize=3, linewidth=1.0,
    )
    ax.axvline(0, linestyle="--", linewidth=1)
    ax.axhline(0, linestyle="--", linewidth=1)
    ax.set_xlabel(f"{x_persona} ideology shift: final minus initial")
    ax.set_ylabel(f"{y_persona} ideology shift: final minus initial")
    ax.set_title("DTAG persona-specific ideology shifts by question-set theme")
    ax.grid(True, alpha=0.25)
    for _, r in plot_df.iterrows():
        text = str(int(r["num"])) if numbered else str(r["label"])
        ax.annotate(text, (r[x_persona], r[y_persona]), xytext=(5, 5), textcoords="offset points", fontsize=9 if numbered else 8)
    # CM/WF-specific quadrant annotations when present.
    if x_persona == "CM" and y_persona == "WF":
        xmin, xmax = ax.get_xlim(); ymin, ymax = ax.get_ylim()
        xr = xmax - xmin; yr = ymax - ymin
        ax.text(xmin + 0.015*xr, ymax - 0.035*yr, "Convergence:\nCM leftward, WF rightward", ha="left", va="top", fontsize=9)
        ax.text(xmax - 0.015*xr, ymin + 0.035*yr, "Divergence:\nCM rightward, WF leftward", ha="right", va="bottom", fontsize=9)
        ax.text(xmax - 0.015*xr, ymax - 0.035*yr, "Shared rightward shift:\nCM hardens, WF moderates", ha="right", va="top", fontsize=9)
        ax.text(xmin + 0.015*xr, ymin + 0.035*yr, "Shared leftward shift:\nCM moderates, WF hardens", ha="left", va="bottom", fontsize=9)
    fig.tight_layout()
    suffix = "numbered" if numbered else "full_labels"
    save_plot_figure(fig, out / f"dtag_quadrant_{suffix}_{safe_name(variant)}", dpi=dpi, transparent=transparent, pdf=pdf)
    plt.close(fig)
    return 1, plot_df


def zip_directory(src_dir: Path, zip_path: Path) -> None:
    import zipfile
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src_dir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src_dir.parent))


def make_integrated_plots(
    post_dir: Path,
    ideology_long: pd.DataFrame,
    run_level: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    plot_dir = mkdir(Path(args.plot_dir) if getattr(args, "plot_dir", "") else post_dir / "plots")
    label_map = load_label_map(getattr(args, "label_map_csv", ""))
    variants = [v.strip() for v in str(args.plot_variant).split(",") if v.strip()]
    if not variants:
        variants = ["forward"]
    plot_counts: Dict[str, object] = {}
    for variant in variants:
        ntraj = make_confidence_trajectory_plots(
            ideology_long=ideology_long,
            plot_dir=plot_dir,
            variant=variant,
            ci=float(args.plot_ci),
            dpi=int(args.plot_dpi),
            dark=bool(args.dark),
            transparent=bool(args.transparent),
            pdf=bool(args.pdf),
            show_replicates=bool(args.show_replicates),
            band_alpha=float(args.band_alpha),
            grid_alpha=float(args.grid_alpha),
            traj_width=float(args.traj_width),
            traj_height=float(args.traj_height),
            label_map=label_map,
        )
        nsum, _ = make_confidence_summary_plots(
            run_level=run_level,
            plot_dir=plot_dir,
            variant=variant,
            ci=float(args.plot_ci),
            dpi=int(args.plot_dpi),
            dark=bool(args.dark),
            transparent=bool(args.transparent),
            pdf=bool(args.pdf),
            grid_alpha=float(args.grid_alpha),
            summary_width=float(args.summary_width),
            summary_height=float(args.summary_height),
            label_map=label_map,
        )
        plot_counts[f"{variant}_trajectory_plots"] = ntraj
        plot_counts[f"{variant}_summary_plots"] = nsum
    if bool(args.quadrant_plot):
        q_variant = str(args.quadrant_variant)
        nq, _ = make_quadrant_summary_plot(
            run_level=run_level,
            plot_dir=plot_dir,
            variant=q_variant,
            ci=float(args.plot_ci),
            dpi=int(args.plot_dpi),
            dark=bool(args.dark),
            transparent=bool(args.transparent),
            pdf=bool(args.pdf),
            label_map=label_map,
            numbered=not bool(args.quadrant_full_labels),
        )
        plot_counts[f"quadrant_{q_variant}_plots"] = nq
        if bool(args.quadrant_full_labels):
            nq2, _ = make_quadrant_summary_plot(
                run_level=run_level,
                plot_dir=plot_dir,
                variant=q_variant,
                ci=float(args.plot_ci),
                dpi=int(args.plot_dpi),
                dark=bool(args.dark),
                transparent=bool(args.transparent),
                pdf=bool(args.pdf),
                label_map=label_map,
                numbered=False,
            )
            plot_counts[f"quadrant_{q_variant}_full_label_plots"] = nq2
    if bool(args.zip_plots):
        zip_directory(plot_dir, plot_dir.with_suffix(".zip"))
        plot_counts["zip"] = str(plot_dir.with_suffix(".zip"))
    (plot_dir / "plot_config.json").write_text(json.dumps({
        "plot_dir": str(plot_dir),
        "plot_variant": str(args.plot_variant),
        "quadrant_variant": str(args.quadrant_variant),
        "plot_ci": float(args.plot_ci),
        "dark": bool(args.dark),
        "transparent": bool(args.transparent),
        "pdf": bool(args.pdf),
        "label_map_csv": str(args.label_map_csv),
        "counts": plot_counts,
    }, indent=2), encoding="utf-8")
    print(f"plots: {plot_dir}")
    if bool(args.zip_plots):
        print(f"plots_zip: {plot_dir.with_suffix('.zip')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Postprocess DTAG outputs for regression-to-center and divergent movements.")
    ap.add_argument("--batch_out", required=True, help="Batch output directory containing runs_index.csv")
    ap.add_argument("--post_dir", default="", help="Output directory for postprocessed files. Default: <batch_out>/postprocess")
    ap.add_argument("--center_mode", default="zero", choices=["zero", "global_initial", "persona_initial", "question_set_initial", "persona_question_initial"], help="Reference center for regression-to-mean tests")
    ap.add_argument("--center", type=float, default=0.0, help="Center value used when --center_mode zero")
    ap.add_argument("--epsilon", type=float, default=1e-9, help="Numerical tolerance for no movement")
    ap.add_argument("--effect_threshold", type=float, default=0.005, help="Minimum effect size to flag meaningful movement")
    ap.add_argument("--min_reps", type=int, default=2, help="Minimum runs in a condition to include in summaries/flags")
    ap.add_argument("--bootstrap", type=int, default=2000, help="Bootstrap replicates for mean CI. Use 0 to disable.")
    ap.add_argument("--seed", type=int, default=123, help="Random seed for bootstrap CIs")
    ap.add_argument("--make_plots", action="store_true", help="Write basic diagnostic plots")
    ap.add_argument("--plot_dir", default="", help="Output directory for integrated plots. Default: <post_dir>/plots")
    ap.add_argument("--plot_variant", default="forward", help="Comma-separated variants for trajectory/summary plots, e.g. forward or forward,reverse,shuffle or all")
    ap.add_argument("--quadrant_plot", action="store_true", help="Write CM-vs-WF quadrant summary plot")
    ap.add_argument("--quadrant_variant", default="all", help="Variant aggregation for quadrant plot: all, forward, reverse, shuffle, etc.")
    ap.add_argument("--quadrant_full_labels", action="store_true", help="Use full text labels on quadrant plot instead of numbered labels")
    ap.add_argument("--label_map_csv", default="", help="Optional CSV mapping question_set to interpretive_name/label")
    ap.add_argument("--plot_ci", type=float, default=0.95, help="Confidence interval for plots")
    ap.add_argument("--plot_dpi", type=int, default=220, help="Plot DPI")
    ap.add_argument("--dark", action="store_true", help="Use light text/axes for dark backgrounds")
    ap.add_argument("--transparent", action="store_true", help="Save transparent-background plots")
    ap.add_argument("--pdf", action="store_true", help="Also save PDF plots")
    ap.add_argument("--zip_plots", action="store_true", help="Zip the plot directory")
    ap.add_argument("--show_replicates", action="store_true", help="Overlay individual replicate trajectories")
    ap.add_argument("--band_alpha", type=float, default=0.20, help="Confidence band opacity")
    ap.add_argument("--grid_alpha", type=float, default=0.25, help="Grid opacity")
    ap.add_argument("--traj_width", type=float, default=7.5, help="Trajectory plot width")
    ap.add_argument("--traj_height", type=float, default=4.5, help="Trajectory plot height")
    ap.add_argument("--summary_width", type=float, default=11.0, help="Summary plot width")
    ap.add_argument("--summary_height", type=float, default=4.5, help="Summary plot base height")
    args = ap.parse_args()

    batch_out, runs_index_path = resolve_batch_out_and_index(args.batch_out)
    if not batch_out.exists():
        raise SystemExit(f"batch_out not found: {batch_out}")

    post_dir = mkdir(args.post_dir if args.post_dir else batch_out / "postprocess")

    rebuilt_index = False
    if runs_index_path is not None and runs_index_path.exists():
        runs_index = pd.read_csv(runs_index_path, dtype=str).fillna("")
    else:
        print(f"WARNING: runs_index.csv not found under {batch_out}; rebuilding from jobs_planned.csv and run directories.", file=sys.stderr)
        runs_index = rebuild_runs_index_from_planned(batch_out).fillna("")
        rebuilt_index = True
        runs_index_path = post_dir / "runs_index_rebuilt.csv"
        runs_index.to_csv(runs_index_path, index=False)
    if "status" in runs_index.columns:
        runs = runs_index[runs_index["status"] == "ok"].copy()
    else:
        runs = runs_index.copy()

    ideology_rows: List[pd.DataFrame] = []
    run_rows: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []

    for _, row in runs.iterrows():
        df = load_run_ideology(row, batch_out=batch_out)
        job_id = str(row.get("job_id", ""))
        if df is None or df.empty:
            skipped.append({"job_id": job_id, "reason": "missing_or_bad_ideology_csv", "run_dir": row.get("run_dir", "")})
            continue

        persona_id = str(row.get("persona_id", ""))
        qset = str(row.get("question_set", ""))
        variant = str(row.get("variant", ""))
        rep = row.get("replicate", "")
        seed = row.get("seed", "")

        dfl = df.copy()
        dfl["job_id"] = job_id
        dfl["persona_id"] = persona_id
        dfl["question_set"] = qset
        dfl["question_set_type"] = parse_qset_type(qset)
        dfl["variant"] = variant
        dfl["replicate"] = rep
        dfl["seed"] = seed
        ideology_rows.append(dfl)

        initial = float(df.iloc[0]["ideology_index"])
        final = float(df.iloc[-1]["ideology_index"])
        delta = final - initial
        slope = slope_from_series(df)
        run_rows.append({
            "job_id": job_id,
            "persona_id": persona_id,
            "question_set": qset,
            "question_set_type": parse_qset_type(qset),
            "variant": variant,
            "replicate": rep,
            "seed": seed,
            "n_steps": int(df.shape[0] - 1),  # step 0 is initial state
            "initial": initial,
            "final": final,
            "delta": delta,
            "slope_per_step": slope,
            "min_ideology": float(df["ideology_index"].min()),
            "max_ideology": float(df["ideology_index"].max()),
            "trajectory_range": float(df["ideology_index"].max() - df["ideology_index"].min()),
            "stdout_path": row.get("stdout_path", ""),
            "run_dir": row.get("run_dir", ""),
            "meta_json": row.get("meta_json", ""),
            "ideology_csv": row.get("ideology_csv", ""),
            "questions_csv": row.get("questions_csv", ""),
            "final_state_json": row.get("final_state_json", ""),
        })

    if ideology_rows:
        ideology_long = pd.concat(ideology_rows, ignore_index=True)
    else:
        ideology_long = pd.DataFrame()
    run_level = pd.DataFrame(run_rows)
    skipped_df = pd.DataFrame(skipped)

    if run_level.empty:
        runs_index.to_csv(post_dir / "runs_index_input.csv", index=False)
        skipped_df.to_csv(post_dir / "skipped_runs.csv", index=False)
        raise SystemExit(f"No usable ideology runs found. Wrote skipped_runs.csv to {post_dir}")

    centers = choose_centers(run_level, mode=args.center_mode, center_value=float(args.center))
    run_level["center"] = centers
    run_level["initial_distance"] = (run_level["initial"] - run_level["center"]).abs()
    run_level["final_distance"] = (run_level["final"] - run_level["center"]).abs()
    run_level["distance_change"] = run_level["final_distance"] - run_level["initial_distance"]
    run_level["movement"] = run_level["distance_change"].apply(lambda x: movement_label(float(x), args.epsilon))
    run_level["signed_delta_direction"] = run_level["delta"].apply(lambda x: signed_delta_label(float(x), args.epsilon))
    run_level["away_from_center"] = run_level["movement"].eq("away_from_center")
    run_level["toward_center"] = run_level["movement"].eq("toward_center")
    run_level["meaningful_distance_change"] = run_level["distance_change"].abs() >= float(args.effect_threshold)
    run_level["meaningful_signed_delta"] = run_level["delta"].abs() >= float(args.effect_threshold)

    # Join run-level center into long table for optional downstream plotting.
    ideology_long = ideology_long.merge(run_level[["job_id", "center"]], on="job_id", how="left")
    ideology_long["distance_to_center"] = (ideology_long["ideology_index"] - ideology_long["center"]).abs()

    group_cols = ["persona_id", "question_set", "variant"]
    condition_summary = make_condition_summary(run_level, group_cols, args.epsilon, args.effect_threshold, args.bootstrap, args.seed)
    if not condition_summary.empty:
        condition_summary = condition_summary[condition_summary["n_runs"] >= int(args.min_reps)].copy()
        condition_summary["question_set_type"] = condition_summary["question_set"].apply(parse_qset_type)

    # Summarize at topic/question-set level across order variants.
    topic_summary = make_condition_summary(run_level, ["persona_id", "question_set"], args.epsilon, args.effect_threshold, args.bootstrap, args.seed + 1000)
    if not topic_summary.empty:
        topic_summary = topic_summary[topic_summary["n_runs"] >= int(args.min_reps)].copy()
        topic_summary["question_set_type"] = topic_summary["question_set"].apply(parse_qset_type)

    step_summary = make_step_summary(ideology_long) if not ideology_long.empty else pd.DataFrame()
    order_sensitivity = make_order_sensitivity(condition_summary, effect_threshold=args.effect_threshold)
    cross_persona = make_cross_persona_divergence(condition_summary, effect_threshold=args.effect_threshold)

    regression_flags = condition_summary.copy()
    if not regression_flags.empty:
        regression_flags = regression_flags.sort_values(["regression_flag", "mean_distance_change"], ascending=[True, True])

    divergence_parts = []
    if not condition_summary.empty:
        div_conditions = condition_summary[
            condition_summary["regression_flag"].isin(["consistent_away_from_center", "mixed_replicate_directions", "mostly_away_from_center"])
            | condition_summary["signed_delta_flag"].isin(["mixed_left_right"])
        ].copy()
        div_conditions["divergence_type"] = "within_condition_or_away_from_center"
        divergence_parts.append(div_conditions)
    divergence_flags = pd.concat(divergence_parts, ignore_index=True) if divergence_parts else pd.DataFrame()

    # Write all outputs.
    runs_index.to_csv(post_dir / "runs_index_input.csv", index=False)
    ideology_long.to_csv(post_dir / "ideology_long.csv", index=False)
    run_level.to_csv(post_dir / "run_level.csv", index=False)
    skipped_df.to_csv(post_dir / "skipped_runs.csv", index=False)
    condition_summary.to_csv(post_dir / "condition_summary.csv", index=False)
    topic_summary.to_csv(post_dir / "topic_summary.csv", index=False)
    step_summary.to_csv(post_dir / "step_summary.csv", index=False)
    regression_flags.to_csv(post_dir / "regression_to_mean_flags.csv", index=False)
    divergence_flags.to_csv(post_dir / "divergence_flags.csv", index=False)
    order_sensitivity.to_csv(post_dir / "order_sensitivity.csv", index=False)
    cross_persona.to_csv(post_dir / "cross_persona_divergence.csv", index=False)

    config = {
        "batch_out": str(batch_out),
        "post_dir": str(post_dir),
        "center_mode": args.center_mode,
        "center": args.center,
        "epsilon": args.epsilon,
        "effect_threshold": args.effect_threshold,
        "min_reps": args.min_reps,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        "n_runs_index": int(len(runs_index)),
        "n_runs_ok": int(len(runs)),
        "n_runs_analyzed": int(len(run_level)),
        "n_runs_skipped": int(len(skipped_df)),
        "runs_index_rebuilt_from_jobs_planned": bool(rebuilt_index),
    }
    (post_dir / "postprocess_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    write_report(post_dir / "postprocess_report.md", args, runs_index, run_level, condition_summary, order_sensitivity, cross_persona)

    if args.make_plots:
        make_basic_plots(post_dir, condition_summary, run_level)
        make_integrated_plots(post_dir, ideology_long, run_level, args)
    elif args.quadrant_plot:
        # Allow quadrant-only plotting without the old basic diagnostic plots.
        make_integrated_plots(post_dir, ideology_long, run_level, args)

    print("POSTPROCESSING COMPLETE")
    print(f"runs_index: {runs_index_path}")
    print(f"runs analyzed: {len(run_level)}")
    print(f"skipped runs: {len(skipped_df)}")
    print(f"post_dir: {post_dir}")
    print(f"report: {post_dir / 'postprocess_report.md'}")
    print(f"condition_summary: {post_dir / 'condition_summary.csv'}")
    print(f"run_level: {post_dir / 'run_level.csv'}")


if __name__ == "__main__":
    main()
