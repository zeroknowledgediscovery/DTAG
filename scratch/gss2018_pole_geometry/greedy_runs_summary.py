#!/usr/bin/env python3
"""Tables for Experiment.md from greedy_runs/*.csv (no model calls)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
D = HERE / "greedy_runs"


def boot_ci(x, n=4000, seed=0):
    x = np.asarray(x, float)
    if len(x) < 2:
        return float("nan"), float("nan")
    m = np.random.default_rng(seed).choice(x, (n, len(x))).mean(1)
    return float(np.quantile(m, .025)), float(np.quantile(m, .975))


def main():
    out = []
    summary = ["| Persona | Push | J0 | Greedy mean ΔJ (3 runs) | Greedy runs ΔJ | Random mean ΔJ (30) [95% CI] "
               "| Greedy − random | one-sided steps | Audit: full-sweep choice in pool |",
               "|---|---|---:|---:|---|---:|---:|---:|---|"]
    for tag in ("CM_right", "CM_left", "WF_right", "WF_left"):
        f = D / f"{tag}.csv"
        if not f.is_file():
            continue
        df = pd.read_csv(f)
        meta = json.loads((D / f"{tag}.json").read_text())
        J0 = meta["J0"]
        fin = df.groupby(["policy", "run"]).J_after.last() - J0
        g, r = fin.loc["greedy_mu"], fin.loc["random"]
        lo, hi = boot_ci(r)
        gd = df[df.policy == "greedy_mu"]
        aud = meta.get("audit", {})
        summary.append(
            f"| {meta['persona']} | {meta['direction']} | {J0:+.4f} | {g.mean():+.4f} | "
            f"{', '.join(f'{x:+.4f}' for x in g)} | {r.mean():+.4f} [{lo:+.4f}, {hi:+.4f}] | "
            f"{g.mean() - r.mean():+.4f} | {int(gd.one_sided.fillna(False).astype(bool).sum())}/{len(gd)} | "
            f"{aud.get('full_sweep_choice', '?')} ({'yes' if aud.get('in_pool') else 'NO'}) |")
        out.append(f"### {meta['persona']} → {meta['direction']} (J0 = {J0:+.4f})\n")
        for k, run in gd.groupby("run"):
            out.append(f"Greedy run {k}:\n")
            out.append("| step | question | asked because mu | P_up / P_down | drawn answer (p) | ΔJ | J after |")
            out.append("|---:|---|---:|---|---|---:|---:|")
            for x in run.itertuples():
                flag = " (one-sided)" if x.one_sided is True or x.one_sided == "True" else ""
                out.append(f"| {x.step} | {x.variable} — {str(x.question_text)[:45]}{flag} | {x.expected_delta:+.4f} | "
                           f"{x.P_up:.2f} / {x.P_down:.2f} | {x.answer} ({x.p_answer:.2f}) | {x.delta_I:+.4f} | "
                           f"{x.J_after:+.4f} |")
            out.append("")
        rs = df[df.policy == "random"]
        mean_path = rs.groupby("step").J_after.mean() - J0
        gpath = gd.groupby("step").J_after.mean() - J0
        out.append("Mean cumulative ΔJ by step (greedy vs random): " + "; ".join(
            f"t{t}: {gpath.get(t, np.nan):+.4f} vs {mean_path.get(t, np.nan):+.4f}" for t in sorted(mean_path.index)))
        out.append("")
    text = "\n".join(["## Summary (ΔJ after all steps)", "", *summary, "", "## Trajectories", "", *out])
    (D / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
