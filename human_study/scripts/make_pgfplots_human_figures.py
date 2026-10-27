#!/usr/bin/env python3
r"""Curate DTAG human study data and write reproducible PGFPlots figures.

The source is the same private GCS human-study archive used by
plot_human_trajectories.py. Right combines original and follow-up participants.
Partial sessions contribute only their measured trajectory steps. Endpoint
boxplots use only sessions completed through adaptive question 20.

Outputs (for --prefix figures/dtag_human):
  figures/dtag_human_trajectory_summary.csv
  figures/dtag_human_endpoint_raw.csv
  figures/dtag_human_endpoint_box_summary.csv
  figures/dtag_human_pgfplots.tex   [two tikzpicture environments]

PGFPlots preamble:
  \usepackage{pgfplots}
  \usepgfplotslibrary{fillbetween,statistics}
  \pgfplotsset{compat=1.18}

Usage from DTAG repository root:
  python3 human_study/scripts/make_pgfplots_human_figures.py --prefix figures/dtag_human
  python3 human_study/scripts/make_pgfplots_human_figures.py --prefix figures/dtag_human --ci-groups all

The script does not write raw participant text, Prolific IDs, or cloud changes.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
from pathlib import Path
from statistics import mean

GROUPS = ("Left", "Right (original + follow-up)", "Neutral", "Random")
LABELS = dict(zip(GROUPS, ("Left", "Right", "Neutral", "Random")))
COLORS = {"Left": "blue", "Right": "red", "Neutral": "black!75", "Random": "green!50!black"}


def load_helper():
    path = Path(__file__).with_name("plot_human_trajectories.py")
    spec = importlib.util.spec_from_file_location("dtag_human_trajectories", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import trajectory loader: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def percentile(xs, p):
    ys = sorted(xs)
    if not ys:
        raise ValueError("Cannot compute percentile of empty data")
    q = (len(ys) - 1) * p / 100.0
    i, j = math.floor(q), math.ceil(q)
    return ys[i] + (ys[j] - ys[i]) * (q - i)


def box_stats(xs):
    ys = sorted(xs)
    q1, med, q3 = (percentile(ys, p) for p in (25, 50, 75))
    spread = q3 - q1
    low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    inside = [v for v in ys if low <= v <= high]
    return {
        "n": len(ys), "mean": mean(ys), "min": ys[0], "q1": q1,
        "median": med, "q3": q3, "max": ys[-1],
        "whisker_lo": inside[0], "whisker_hi": inside[-1],
        "outliers": [v for v in ys if v < low or v > high],
    }


def validate_series(sessions, bands):
    if [r["group"] for r in bands] != list(GROUPS):
        raise ValueError("Unexpected group order from trajectory helper")
    endpoints = {}
    for group in GROUPS:
        endpoints[group] = [s for s in sessions if s["group"] == group
                            and s["status"] == "COMPLETE" and 20 in s["values"]]
        if not endpoints[group]:
            raise ValueError(f"No complete 20-question endpoints for {group}")
    for band in bands:
        values = [s["values"][20] for s in endpoints[band["group"]]]
        counts = band.get("counts", band.get("n_step"))
        if counts is None or len(counts) != 21:
            raise ValueError(f"Unexpected observed counts for {band['group']}")
        if counts[20] != len(values):
            raise ValueError(f"Endpoint n mismatch: {band['group']}")
        if not math.isclose(mean(values), band["mean"][20], abs_tol=1e-10):
            raise ValueError(f"Endpoint mean mismatch: {band['group']}")
    return endpoints


def curate(prefix, sessions, bands, endpoints):
    prefix.parent.mkdir(parents=True, exist_ok=True)
    files = {}
    path = prefix.with_name(prefix.name + "_trajectory_summary.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["arm", "step", "n", "mean_change", "ci95_low", "ci95_high"])
        for group in bands:
            label = LABELS[group["group"]]
            counts = group.get("counts", group.get("n_step"))
            for t in range(21):
                writer.writerow([label, t, counts[t], group["mean"][t], group["low"][t], group["high"][t]])
    files["trajectory"] = path

    path = prefix.with_name(prefix.name + "_endpoint_raw.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["study_id", "session_id", "arm", "question", "index_change"])
        for group in GROUPS:
            for session in sorted(endpoints[group], key=lambda s: (s["study_id"], s["session_id"])):
                writer.writerow([session["study_id"], session["session_id"], LABELS[group], 20, session["values"][20]])
    files["endpoints"] = path

    stats = {g: box_stats([s["values"][20] for s in endpoints[g]]) for g in GROUPS}
    path = prefix.with_name(prefix.name + "_endpoint_box_summary.csv")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["arm", "n", "mean", "min", "q1", "median", "q3", "max", "whisker_lo", "whisker_hi", "outliers"])
        for group in GROUPS:
            b = stats[group]
            writer.writerow([LABELS[group]] + [b[k] for k in ("n", "mean", "min", "q1", "median", "q3", "max", "whisker_lo", "whisker_hi")] +
                            [";".join(f"{v:.9g}" for v in b["outliers"])])
    files["boxes"] = path
    return files, stats


def coordinate_string(points):
    out = []
    for t, v in points:
        if v is not None and math.isfinite(v):
            out.append(f"({t},{v:.10g})")
    return " ".join(out)


def make_tex(bands, stats, ci_groups):
    lines = [
        "% Generated by make_pgfplots_human_figures.py from DTAG archived human observations.",
        "% Preamble: \\usepackage{pgfplots}; \\usepgfplotslibrary{fillbetween,statistics}; \\pgfplotsset{compat=1.18}",
        "% Trajectory: group means +/- pointwise 95% participant-bootstrap CI (shaded only for selected groups).",
        "% Partial sessions contribute observed steps only; no interpolation or imputation.",
        "\\begin{tikzpicture}",
        "\\begin{axis}[",
        "  width=\\linewidth, height=0.58\\linewidth,",
        "  xlabel={Adaptive questions answered}, ylabel={Inferred ideology change from baseline},",
        "  xmin=0, xmax=20, xtick={0,2,...,20},",
        "  ymajorgrids, grid style={gray!20},",
        "  legend style={draw=none,fill=none,font=\\small,at={(0.02,0.98)},anchor=north west},",
        "  legend cell align=left,",
        "]",
        "\\addplot[gray!55,dashed,thin,forget plot] coordinates {(0,0) (20,0)};",
    ]
    n20 = {}
    for band in bands:
        group = band["group"]
        label = LABELS[group]
        color = COLORS[label]
        counts = band.get("counts", band.get("n_step"))
        n20[label] = counts[20]
        if group in ci_groups:
            for boundary, key in (("low", "low"), ("high", "high")):
                xy = coordinate_string(enumerate(band[key]))
                lines.append(f"\\addplot[name path={label.lower()}{boundary},draw=none,forget plot] coordinates {{{xy}}};")
            lines.append(f"\\addplot[{color},fill opacity=0.16,draw opacity=0,forget plot] "
                         f"fill between[of={label.lower()}low and {label.lower()}high];")
        xy = coordinate_string(enumerate(band["mean"]))
        lines.append(f"\\addplot[{color},very thick] coordinates {{{xy}}};")
        lines.append(f"\\addlegendentry{{{label} (n={counts[20]})}}")
    # Legend n refers to Q20: no confusing baseline->endpoint arrows.
    n_label = ", ".join(f"{name}={n20[name]}" for name in ("Left", "Right", "Neutral", "Random"))
    lines += [
        "\\end{axis}",
        "\\end{tikzpicture}",
        "\\par\\medskip",
        "% Legend counts refer to question 20; incomplete trajectories contribute earlier steps only.",
        "% Question-20 observed participant counts: " + n_label,
        "",
        "% Box-and-whisker plots for the same observed final 20-question outcomes.",
        "% Q1/median/Q3 are linearly interpolated percentiles; whiskers are",
        "% most extreme observations inside 1.5 IQR; separate dots mark outliers.",
        "\\begin{tikzpicture}",
        "\\begin{axis}[",
        "  width=\\linewidth, height=0.58\\linewidth,",
        "  ylabel={Inferred ideology change from baseline at question 20},",
        "  xmin=0.5, xmax=4.5, xtick={1,2,3,4},",
        "  xticklabels={" + ",".join(f"{LABELS[g]} (n={stats[g]['n']})" for g in GROUPS) + "},",
        "  ymajorgrids, grid style={gray!20},",
        "  boxplot/draw direction=y,",
        "]",
        "\\addplot[gray!55,dashed,thin,forget plot] coordinates {(0.5,0) (4.5,0)};",
    ]
    for pos, group in enumerate(GROUPS, start=1):
        b = stats[group]
        color = COLORS[LABELS[group]]
        boxparams = ",".join(f"{key}={b[val]:.10g}" for key, val in (("lower whisker", "whisker_lo"),
                          ("lower quartile", "q1"), ("median", "median"),
                          ("upper quartile", "q3"), ("upper whisker", "whisker_hi")))
        lines.append(f"\\addplot+[boxplot prepared={{{boxparams}}},boxplot/draw position={pos},"
                     f"draw={color},fill={color},fill opacity=0.16,forget plot] coordinates {{}};")
        if b["outliers"]:
            xy = coordinate_string((pos, y) for y in b["outliers"])
            lines.append(f"\\addplot+[only marks,mark=*,mark size=1.35pt,draw={color},fill={color},forget plot] "
                         f"coordinates {{{xy}}};")
    lines += [
        "\\end{axis}",
        "\\end{tikzpicture}",
        "% Endpoint counts are also displayed in x-axis labels.",
        "",
    ]
    return "\n".join(lines)


def parse_ci_groups(value):
    names = {"left": GROUPS[0], "right": GROUPS[1], "neutral": GROUPS[2], "random": GROUPS[3]}
    if value == "all":
        return frozenset(GROUPS)
    if value == "none":
        return frozenset()
    chosen = [x.strip().lower() for x in value.split(",")]
    if not chosen or any(x not in names for x in chosen):
        raise argparse.ArgumentTypeError("Use left,right (default), all, none, or comma-separated arm names")
    return frozenset(names[x] for x in chosen)


def build(sessions, summary, prefix, ci_groups):
    endpoints = validate_series(sessions, summary)
    files, box = curate(prefix, sessions, summary, endpoints)
    texfile = prefix.with_name(prefix.name + "_pgfplots.tex")
    texfile.write_text(make_tex(summary, box, ci_groups), encoding="utf-8")
    files["tex"] = texfile
    return files, box


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefix", type=Path, default=Path("dtag_human"))
    ap.add_argument("--bucket", default="pkcsaas-01-dtag-study-data")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--bootstrap", type=int, default=5000)
    ap.add_argument("--ci-groups", type=parse_ci_groups, default=parse_ci_groups("left,right"),
                    help="Which trajectories show shaded 95%% CI: left,right (default), all, none, etc.")
    args = ap.parse_args()
    if not 1 <= args.workers <= 32 or args.bootstrap < 100:
        ap.error("workers must be 1..32 and bootstrap >= 100")
    helper = load_helper()
    sessions = helper.load_sessions(args.bucket, workers=args.workers)
    summary = helper.summarize(sessions, boots=args.bootstrap, complete_only=False)
    outputs, box = build(sessions, summary, args.prefix, args.ci_groups)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    for group in GROUPS:
        print(f"{LABELS[group]}: Q20 n={box[group]['n']}, mean={box[group]['mean']:+.5f}")
    print("PGFPlots: confidence shading only for " + (", ".join(LABELS[g] for g in GROUPS if g in args.ci_groups) or "none"))


if __name__ == "__main__":
    main()
