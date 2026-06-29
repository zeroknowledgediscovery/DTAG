#!/usr/bin/env python3
"""
plot_dtag_ideology_confidence.py

Generate DTAG ideology trajectory plots with confidence bounds, stratified by
persona and question set.

Expected input: a long-format CSV with at least:
  step
  ideology_index
  persona_id
  question_set
  variant
  job_id or replicate/run identifier

This matches the ideology_long.csv produced by the DTAG postprocessing workflow.

Examples:

  # Standard white-background plots
  python3 plot_dtag_ideology_confidence.py \
    --input ideology_long.csv \
    --outdir dtag_confidence_plots \
    --variant forward

  # Dark plots
  python3 plot_dtag_ideology_confidence.py \
    --input ideology_long.csv \
    --outdir dtag_confidence_plots_dark \
    --variant forward \
    --dark

  # Dark transparent plots for slides
  python3 plot_dtag_ideology_confidence.py \
    --input ideology_long.csv \
    --outdir dtag_confidence_plots_dark_transparent \
    --variant forward \
    --dark \
    --transparent

  # Write both PNG and PDF, then zip outputs
  python3 plot_dtag_ideology_confidence.py \
    --input ideology_long.csv \
    --outdir dtag_confidence_plots \
    --variant forward \
    --pdf \
    --zip

Notes:
  --dark changes text, axes, and grid colors for dark backgrounds.
  --transparent saves figures with transparent backgrounds. Combining
  --dark --transparent gives light plot text on transparent background,
  useful for dark slides.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def safe_name(s: object) -> str:
    s = str(s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "item"


def prettify_qset(q: object) -> str:
    s = str(q)
    s = s.replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def infer_col(df: pd.DataFrame, candidates: List[str], required: bool = True) -> str:
    cols_lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if not c:
            continue
        if c in df.columns:
            return c
        if c.lower() in cols_lower:
            return cols_lower[c.lower()]
    if required:
        raise ValueError(
            f"Could not infer required column. Tried: {candidates}. "
            f"Available columns: {list(df.columns)}"
        )
    return ""


def normal_z_for_ci(ci: float) -> float:
    """Return approximate z-score for common CI levels without requiring scipy."""
    ci = float(ci)
    table = {
        0.80: 1.2815515655446004,
        0.90: 1.6448536269514722,
        0.95: 1.959963984540054,
        0.98: 2.3263478740408408,
        0.99: 2.5758293035489004,
    }
    closest = min(table.keys(), key=lambda k: abs(k - ci))
    if abs(closest - ci) < 1e-9:
        return table[closest]
    print(f"WARNING: unsupported --ci {ci}; using 0.95", file=sys.stderr)
    return table[0.95]


def mean_ci(x: Iterable[object], ci: float = 0.95) -> Tuple[float, float, float, int, float]:
    vals = pd.to_numeric(pd.Series(list(x)), errors="coerce").dropna().to_numpy(dtype=float)
    n = len(vals)
    if n == 0:
        return (np.nan, np.nan, np.nan, 0, np.nan)
    m = float(np.mean(vals))
    sd = float(np.std(vals, ddof=1)) if n > 1 else 0.0
    z = normal_z_for_ci(ci)
    half = z * sd / math.sqrt(n) if n > 1 else 0.0
    return (m, m - half, m + half, n, sd)


def grouped_mean_ci(df: pd.DataFrame, group_cols: List[str], value_col: str, ci: float) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(group_cols, sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        m, lo, hi, n, sd = mean_ci(g[value_col], ci=ci)
        row = {c: v for c, v in zip(group_cols, key)}
        row.update({"mean": m, "lower": lo, "upper": hi, "n": n, "sd": sd})
        rows.append(row)
    return pd.DataFrame(rows)


def set_plot_theme(dark: bool, transparent: bool):
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


def save_figure(fig, path_base: Path, dpi: int, transparent: bool, pdf: bool):
    png_path = path_base.with_suffix(".png")
    fig.savefig(png_path, dpi=dpi, transparent=transparent, bbox_inches="tight")
    if pdf:
        fig.savefig(path_base.with_suffix(".pdf"), transparent=transparent, bbox_inches="tight")


def load_and_normalize(args) -> pd.DataFrame:
    df = pd.read_csv(args.input)

    step_col = infer_col(df, [args.step_col, "step", "query_idx", "iteration"])
    value_col = infer_col(df, [args.value_col, "ideology_index", "ideology", "score"])
    persona_col = infer_col(df, [args.persona_col, "persona_short", "persona_id", "persona"])
    qset_col = infer_col(df, [args.question_set_col, "question_set", "question_file", "source_set"])
    variant_col = infer_col(df, [args.variant_col, "variant", "order_variant"], required=False)
    job_col = infer_col(df, [args.job_col, "job_id", "run_id", "replicate", "rep"], required=False)

    out = df.copy()
    out["step"] = pd.to_numeric(out[step_col], errors="coerce")
    out["ideology_index"] = pd.to_numeric(out[value_col], errors="coerce")
    out["persona_id"] = out[persona_col].astype(str)
    out["question_set"] = out[qset_col].astype(str)
    out["variant"] = out[variant_col].astype(str) if variant_col else "forward"

    if job_col:
        out["job_id"] = out[job_col].astype(str)
    else:
        out["job_id"] = (
            out["persona_id"].astype(str)
            + "__" + out["question_set"].astype(str)
            + "__" + out["variant"].astype(str)
            + "__synthetic"
        )

    extracted = out["persona_id"].str.extract(r"^(WF|CM|[A-Z]{2,4})", expand=False)
    out["persona_short"] = extracted.fillna(out["persona_id"])

    out = out.dropna(subset=["step", "ideology_index"]).copy()
    out["step"] = out["step"].astype(int)

    if "center" in df.columns:
        out["center"] = pd.to_numeric(df["center"], errors="coerce").fillna(float(args.center))
    else:
        out["center"] = float(args.center)

    return out


def make_trajectory_plots(df: pd.DataFrame, args, outdir: Path) -> int:
    traj_dir = outdir / f"trajectories_{safe_name(args.variant)}"
    traj_dir.mkdir(parents=True, exist_ok=True)

    nplots = 0
    for (persona, qset), g in df.groupby(["persona_short", "question_set"], sort=True):
        summary = grouped_mean_ci(g, ["step"], "ideology_index", ci=args.ci).sort_values("step")
        if summary.empty:
            continue

        x = summary["step"].to_numpy(dtype=float)
        y = summary["mean"].to_numpy(dtype=float)
        lo = summary["lower"].to_numpy(dtype=float)
        hi = summary["upper"].to_numpy(dtype=float)

        fig, ax = plt.subplots(figsize=(args.traj_width, args.traj_height))
        ax.plot(x, y, marker="o", linewidth=2, label="Mean ideology index")
        ax.fill_between(x, lo, hi, alpha=args.band_alpha, label=f"{int(args.ci*100)}% CI")
        ax.axhline(float(args.center), linestyle="--", linewidth=1)
        if args.show_replicates:
            for _, rg in g.groupby("job_id"):
                rg = rg.sort_values("step")
                ax.plot(rg["step"], rg["ideology_index"], linewidth=0.8, alpha=0.25)

        ax.set_title(f"{persona}: {prettify_qset(qset)}")
        ax.set_xlabel("Question step")
        ax.set_ylabel("Ideology index")
        ax.legend(frameon=False)
        ax.grid(True, alpha=args.grid_alpha)
        fig.tight_layout()

        fbase = traj_dir / f"trajectory_{safe_name(persona)}__{safe_name(qset)}__{safe_name(args.variant)}"
        save_figure(fig, fbase, dpi=args.dpi, transparent=args.transparent, pdf=args.pdf)
        plt.close(fig)
        nplots += 1

    return nplots


def compute_endpoints(all_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (job_id, persona, qset, variant), g in all_df.groupby(
        ["job_id", "persona_short", "question_set", "variant"], sort=False
    ):
        g = g.sort_values("step")
        if g.empty:
            continue
        center = float(g.iloc[0]["center"])
        initial = float(g.iloc[0]["ideology_index"])
        final = float(g.iloc[-1]["ideology_index"])
        rows.append({
            "job_id": job_id,
            "persona": persona,
            "question_set": qset,
            "variant": variant,
            "n_steps": int(g["step"].nunique()),
            "initial": initial,
            "final": final,
            "signed_delta": final - initial,
            "center": center,
            "initial_distance_to_center": abs(initial - center),
            "final_distance_to_center": abs(final - center),
            "distance_change": abs(final - center) - abs(initial - center),
            "moved_toward_center": abs(final - center) < abs(initial - center),
            "moved_away_from_center": abs(final - center) > abs(initial - center),
        })
    return pd.DataFrame(rows)


def summarize_conditions(endpoints: pd.DataFrame, ci: float) -> pd.DataFrame:
    rows = []
    for (persona, qset), g in endpoints.groupby(["persona", "question_set"], sort=True):
        row = {"persona": persona, "question_set": qset, "n_runs": int(g["job_id"].nunique())}
        for col in ["initial", "final", "signed_delta", "distance_change"]:
            m, lo, hi, n, sd = mean_ci(g[col], ci=ci)
            row[f"{col}_mean"] = m
            row[f"{col}_lower"] = lo
            row[f"{col}_upper"] = hi
            row[f"{col}_sd"] = sd
        row["frac_toward_center"] = float(g["moved_toward_center"].mean())
        row["frac_away_from_center"] = float(g["moved_away_from_center"].mean())
        row["signed_direction"] = (
            "rightward" if row["signed_delta_mean"] > 0
            else "leftward" if row["signed_delta_mean"] < 0
            else "flat"
        )
        row["mean_reversion_signal"] = bool(row["distance_change_mean"] < -0.005)
        row["away_from_center_signal"] = bool(row["distance_change_mean"] > 0.005)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["persona", "question_set"])


def make_summary_plots(summary: pd.DataFrame, args, outdir: Path) -> int:
    summary_dir = outdir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    nplots = 0
    for persona, g in summary.groupby("persona", sort=True):
        gg = g.sort_values("signed_delta_mean")
        yloc = np.arange(len(gg))
        y = gg["signed_delta_mean"].to_numpy(dtype=float)
        lo = gg["signed_delta_lower"].to_numpy(dtype=float)
        hi = gg["signed_delta_upper"].to_numpy(dtype=float)

        fig, ax = plt.subplots(figsize=(args.summary_width, max(args.summary_height, 0.35 * len(gg) + 2)))
        ax.errorbar(y, yloc, xerr=[y - lo, hi - y], fmt="o", capsize=3)
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.set_yticks(yloc)
        ax.set_yticklabels([prettify_qset(q) for q in gg["question_set"]])
        ax.set_xlabel("Final minus initial ideology index")
        ax.set_ylabel("Question set")
        ax.set_title(f"{persona}: {args.variant} signed ideology shift with {int(args.ci*100)}% CI")
        ax.grid(True, axis="x", alpha=args.grid_alpha)
        fig.tight_layout()

        fbase = summary_dir / f"summary_signed_delta_{safe_name(persona)}__{safe_name(args.variant)}"
        save_figure(fig, fbase, dpi=args.dpi, transparent=args.transparent, pdf=args.pdf)
        plt.close(fig)
        nplots += 1

        gg = g.sort_values("distance_change_mean")
        yloc = np.arange(len(gg))
        y = gg["distance_change_mean"].to_numpy(dtype=float)
        lo = gg["distance_change_lower"].to_numpy(dtype=float)
        hi = gg["distance_change_upper"].to_numpy(dtype=float)

        fig, ax = plt.subplots(figsize=(args.summary_width, max(args.summary_height, 0.35 * len(gg) + 2)))
        ax.errorbar(y, yloc, xerr=[y - lo, hi - y], fmt="o", capsize=3)
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.set_yticks(yloc)
        ax.set_yticklabels([prettify_qset(q) for q in gg["question_set"]])
        ax.set_xlabel("Change in distance to center; negative means toward center")
        ax.set_ylabel("Question set")
        ax.set_title(f"{persona}: {args.variant} regression-to-mean diagnostic with {int(args.ci*100)}% CI")
        ax.grid(True, axis="x", alpha=args.grid_alpha)
        fig.tight_layout()

        fbase = summary_dir / f"summary_distance_change_{safe_name(persona)}__{safe_name(args.variant)}"
        save_figure(fig, fbase, dpi=args.dpi, transparent=args.transparent, pdf=args.pdf)
        plt.close(fig)
        nplots += 1

    return nplots


def make_cross_persona_table(summary: pd.DataFrame, outdir: Path, variant: str) -> pd.DataFrame:
    summary_dir = outdir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    wide = summary.pivot(index="question_set", columns="persona", values="signed_delta_mean").reset_index()
    personas = [c for c in wide.columns if c != "question_set"]

    if len(personas) >= 2:
        flags = []
        gaps = []
        for _, row in wide.iterrows():
            vals = [row[p] for p in personas if pd.notna(row[p])]
            signs = [np.sign(v) for v in vals if v != 0]
            flags.append((len(set(signs)) > 1) if signs else False)
            if "CM" in wide.columns and "WF" in wide.columns:
                gaps.append(row["CM"] - row["WF"])
            else:
                gaps.append(np.nan)
        wide["opposite_signed_direction"] = flags
        wide["delta_gap_CM_minus_WF"] = gaps
    else:
        wide["opposite_signed_direction"] = False
        wide["delta_gap_CM_minus_WF"] = np.nan

    wide.to_csv(summary_dir / f"cross_persona_{safe_name(variant)}_divergence.csv", index=False)
    return wide


def zip_outputs(outdir: Path) -> Path:
    zip_path = outdir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(outdir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(outdir.parent))
    return zip_path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Long-format ideology CSV")
    ap.add_argument("--outdir", default="dtag_confidence_plots", help="Output directory")

    ap.add_argument("--variant", default="forward",
                    help="Variant/order to plot, e.g. forward, reverse, shuffle. Use 'all' to include all rows in trajectories.")
    ap.add_argument("--center", type=float, default=0.0, help="Center used for regression-to-mean diagnostic")

    ap.add_argument("--ci", type=float, default=0.95, help="Confidence interval level: 0.80, 0.90, 0.95, 0.98, 0.99")
    ap.add_argument("--dpi", type=int, default=220)
    ap.add_argument("--pdf", action="store_true", help="Also write PDF outputs")
    ap.add_argument("--zip", action="store_true", help="Zip the output directory after plotting")

    ap.add_argument("--dark", action="store_true", help="Use light text/axes suitable for dark backgrounds")
    ap.add_argument("--transparent", action="store_true", help="Save transparent-background figures")
    ap.add_argument("--show_replicates", action="store_true", help="Overlay individual replicate trajectories faintly")

    ap.add_argument("--band_alpha", type=float, default=0.20)
    ap.add_argument("--grid_alpha", type=float, default=0.25)

    ap.add_argument("--traj_width", type=float, default=7.5)
    ap.add_argument("--traj_height", type=float, default=4.5)
    ap.add_argument("--summary_width", type=float, default=11.0)
    ap.add_argument("--summary_height", type=float, default=4.5)

    ap.add_argument("--step_col", default="")
    ap.add_argument("--value_col", default="")
    ap.add_argument("--persona_col", default="")
    ap.add_argument("--question_set_col", default="")
    ap.add_argument("--variant_col", default="")
    ap.add_argument("--job_col", default="")

    return ap.parse_args()


def main():
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    set_plot_theme(dark=args.dark, transparent=args.transparent)

    all_df = load_and_normalize(args)

    if args.variant.lower() == "all":
        plot_df = all_df.copy()
        variant_label = "all"
    else:
        plot_df = all_df[all_df["variant"] == args.variant].copy()
        variant_label = args.variant

    if plot_df.empty:
        variants = sorted(all_df["variant"].dropna().astype(str).unique())
        raise SystemExit(f"No rows found for --variant {args.variant!r}. Available variants: {variants}")

    args.variant = variant_label

    ntraj = make_trajectory_plots(plot_df, args, outdir)

    endpoints_all = compute_endpoints(all_df)
    endpoints_variant = endpoints_all if args.variant == "all" else endpoints_all[endpoints_all["variant"] == args.variant].copy()

    summary = summarize_conditions(endpoints_variant, ci=args.ci)
    summary_dir = outdir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    endpoints_all.to_csv(summary_dir / "run_endpoints_all_variants.csv", index=False)
    endpoints_variant.to_csv(summary_dir / f"run_endpoints_{safe_name(args.variant)}.csv", index=False)
    summary.to_csv(summary_dir / f"condition_summary_{safe_name(args.variant)}.csv", index=False)

    make_cross_persona_table(summary, outdir, args.variant)
    nsummary = make_summary_plots(summary, args, outdir)

    report = []
    report.append("# DTAG ideology confidence plots\n")
    report.append(f"Input: `{args.input}`\n")
    report.append(f"Variant plotted: `{args.variant}`\n")
    report.append(f"Rows used for trajectory plots: {len(plot_df)}\n")
    report.append(f"Trajectory plots: {ntraj}\n")
    report.append(f"Summary plots: {nsummary}\n")
    report.append(f"Dark mode: {args.dark}\n")
    report.append(f"Transparent background: {args.transparent}\n")
    report.append("\n## Strongest movement away from center\n")
    if not summary.empty:
        cols = ["persona", "question_set", "n_runs", "initial_mean", "final_mean", "signed_delta_mean", "distance_change_mean"]
        tmp = summary.sort_values("distance_change_mean", ascending=False).head(10)
        report.append(tmp[cols].to_markdown(index=False))
        report.append("\n\n## Strongest movement toward center\n")
        tmp = summary.sort_values("distance_change_mean", ascending=True).head(10)
        report.append(tmp[cols].to_markdown(index=False))
    (summary_dir / f"plot_report_{safe_name(args.variant)}.md").write_text("\n".join(report), encoding="utf-8")

    zip_path = None
    if args.zip:
        zip_path = zip_outputs(outdir)

    print(f"Input rows: {len(all_df)}")
    print(f"Trajectory rows plotted: {len(plot_df)}")
    print(f"Condition summaries: {len(summary)}")
    print(f"Trajectory plots written: {ntraj}")
    print(f"Summary plots written: {nsummary}")
    print(f"Output directory: {outdir.resolve()}")
    if zip_path:
        print(f"Zip file: {zip_path.resolve()}")


if __name__ == "__main__":
    main()
