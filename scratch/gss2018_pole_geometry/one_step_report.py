#!/usr/bin/env python3
"""Summarize one_step_enumeration.py outputs into ONE_STEP_REPORT.md (no model calls).

    python scratch/gss2018_pole_geometry/one_step_report.py [--compare-parallel DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RES = HERE / "one_step_results"  # committed copy of results/one_step_enumeration
sys.path.insert(0, str(HERE.parents[1]))
from optimizer.one_step_geometry import summarize_variable  # noqa: E402


def fmt(x):
    return f"{x:+.5f}"


def table(df, cols, n):
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for _, r in df.head(n).iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (float, np.floating)):
                cells.append(f"{v:.3f}" if c.startswith(("p", "P")) else fmt(v))
            else:
                cells.append(str(v).replace("|", "/")[:60])
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def augment(s, r):
    """Add P_up, P_down, P_zero, one_sided (shared definition with optimizer.one_step_geometry)."""
    extra = pd.DataFrame([{k: v for k, v in summarize_variable(var, g.to_dict("records")).items()
                           if k in ("variable", "P_up", "P_down", "P_zero", "one_sided")}
                          for var, g in r.groupby("variable", sort=False)])
    s = s.drop(columns=[c for c in ("P_up", "P_down", "P_zero", "one_sided") if c in s], errors="ignore")
    return s.merge(extra, on="variable", how="left")


MU_COLS = ["rank", "direction", "variable", "is_pole_item", "expected_delta", "sd", "P_up", "P_down",
           "one_sided", "delta_plus", "answer_plus", "p_answer_plus", "delta_minus", "answer_minus",
           "p_answer_minus", "question_text"]


def mu_tables(s, d, k=25):
    """mu_rankings.csv: top-k argmax / argmin of mu, separately for non-pole and pole items."""
    out = []
    for pole in (False, True):
        g = s[s.is_pole_item == pole]
        for direction, asc in (("argmax_mu", False), ("argmin_mu", True)):
            top = g.sort_values(["expected_delta", "variable"], ascending=[asc, True]).head(k).copy()
            top.insert(0, "direction", direction)
            top.insert(0, "rank", range(1, len(top) + 1))
            out.append(top)
    pd.concat(out)[MU_COLS].to_csv(d / "mu_rankings.csv", index=False)


def ask_tables(s):
    np_, po = s[~s.is_pole_item], s[s.is_pole_item]
    cols = ["variable", "expected_delta", "sd", "P_up", "P_down", "one_sided", "answer_plus",
            "p_answer_plus", "answer_minus", "p_answer_minus"]
    return ["### Which question to ask: argmax mu (push right in expectation), non-pole", "",
            table(np_.sort_values("expected_delta", ascending=False), cols, 10),
            "### Which question to ask: argmin mu (push left in expectation), non-pole", "",
            table(np_.sort_values("expected_delta"), cols, 10),
            "### Pole items: argmax / argmin mu", "",
            table(pd.concat([po.sort_values("expected_delta", ascending=False).head(3),
                             po.sort_values("expected_delta").head(3)]), cols, 6),
            "### argmax Delta / argmin Delta (best case; the answer cannot be chosen), non-pole", "",
            table(pd.concat([np_.sort_values("delta_plus", ascending=False).head(5),
                             np_.sort_values("delta_minus").head(5)]),
                  ["variable", "delta_plus", "answer_plus", "p_answer_plus", "delta_minus", "answer_minus",
                   "p_answer_minus", "expected_delta"], 10)]


def persona_section(name):
    d = RES / name
    meta = json.loads((d / "metadata.json").read_text())
    s = pd.read_csv(d / "variable_summary.csv")
    r = pd.read_csv(d / "response_level.csv")
    s = augment(s, r)
    s.to_csv(d / "variable_summary.csv", index=False)
    mu_tables(s, d)
    v = meta["validation"]
    np_ = s[~s.is_pole_item]
    po = s[s.is_pole_item]
    lines = [f"## {name}", "",
             f"State ({len(meta['state'])} assignments, source: {meta['persona_source']}): "
             f"`{json.dumps(meta['state'])}`", "",
             f"Dropped by 2018 model: {meta['dropped_assignments'] or 'none'}", "",
             f"I(s) = {fmt(meta['I_before'])}, J(s) = {fmt(meta['J_before'])}; "
             f"{meta['n_eligible_variables']} eligible variables "
             f"({meta['n_pole_items_eligible']} pole items), {meta['n_pairs']} (variable, answer) pairs; "
             f"enumeration {meta['seconds_enumeration']:.0f} s "
             f"({1000 * meta['seconds_per_pair']:.1f} ms/pair, workers={meta['workers']}).", "",
             "### Validation", "",
             f"- all answers valid native labels: {v['all_answers_valid']}; persona state valid: {v['persona_state_valid']}",
             f"- I(empty) = {v['empty_offset']:.7f} (matches handoff 0.0600465: {v['empty_offset_matches_handoff']})",
             f"- max |delta_I - delta_J| = {v['max_abs_delta_I_minus_delta_J']:.2e}",
             f"- determinism: {v['determinism_rechecked_pairs']} pairs re-evaluated, max diff "
             f"{v['determinism_max_abs_diff']:.2e}",
             f"- raw native probability sums in [{v['raw_prob_sum_min']:.12f}, {v['raw_prob_sum_max']:.12f}]; "
             f"max off-support mass {v['max_offsupport_mass']:.2e}; "
             f"{len(v['variables_with_offsupport_labels'])} variables with off-support labels; "
             f"{len(v['variables_with_no_positive_probability'])} with no positive on-support probability",
             f"- E[Delta] identity error {v['expected_delta_identity_max_abs_err']:.2e}", "",
             "### Distribution of per-item statistics", "",
             "| set | n | median range | max range | median abs(mu) | max abs(mu) | sum mu | share mu>0 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for lab, g in (("non-pole", np_), ("pole", po), ("all", s)):
        lines.append(f"| {lab} | {len(g)} | {g['range'].median():.5f} | {g['range'].max():.5f} | "
                     f"{g.expected_delta.abs().median():.6f} | {g.expected_delta.abs().max():.5f} | "
                     f"{fmt(g.expected_delta.sum())} | {(g.expected_delta > 0).mean():.2f} |")
    # Low-probability extremes
    big = r[r.delta_I.abs() >= r.delta_I.abs().quantile(0.99)]
    lines += ["", f"Top 1% of |Delta| response rows ({len(big)}): median P(a|s,v) = "
              f"{big.conditional_probability.median():.3f}; share with P < 0.05: "
              f"{(big.conditional_probability < 0.05).mean():.2f}.", "",
              *ask_tables(s),
              "### Largest sensitivity range, non-pole items", "",
              table(np_.sort_values("range", ascending=False),
                    ["variable", "range", "delta_plus", "answer_plus", "p_answer_plus",
                     "delta_minus", "answer_minus", "p_answer_minus", "expected_delta"], 15),
              "### Largest |expected displacement|, non-pole items", "",
              table(np_.reindex(np_.expected_delta.abs().sort_values(ascending=False).index),
                    ["variable", "expected_delta", "sd", "modal_answer", "p_modal", "delta_modal", "range"], 15)]
    return "\n".join(lines), s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare-parallel", type=Path, default=None)
    ap.add_argument("--compare-module", type=Path, default=None,
                    help="optimizer.one_step_geometry --out dir for CM, checked against the reference")
    a = ap.parse_args()
    parts = ["# GSS 2018 exact one-step survey-item response geometry", "",
             "Generated by `one_step_report.py` from `one_step_enumeration.py` outputs.",
             "Native GSS 2018 LSM, original 38-item 2018 poles, J(s) = I(s) - I(empty).",
             "Delta_v(a|s) = I(s u {v=a}) - I(s); mu_v = sum_a P(a|s,v) Delta_v(a|s).",
             "All unassigned variables enumerated; pole items included but flagged and reported separately.",
             "Changes are information-conditioning effects of the model, not opinion change.", "",
             "## Definitions", "",
             "- `delta_I` = Delta_v(a|s) = I(s u {v=a}) - I(s); >0 toward the right pole. Identical in J.",
             "- `delta_plus` = max_a Delta_v(a|s), achieved by `answer_plus` (argmax over answers); "
             "`delta_minus` = min_a Delta_v(a|s), achieved by `answer_minus` (argmin).",
             "- `p` / `conditional_probability` = native P(a|s,v); `p_answer_plus`, `p_answer_minus` = "
             "probability of the extremal answers.",
             "- `expected_delta` = mu_v = sum_a P(a|s,v) Delta_v(a|s): expected move from ASKING v; `sd` its spread.",
             "- `P_up` / `P_down` = probability that the answer moves the index right / left.",
             "- `one_sided` = every answer moves the index the same way (a question effect, not answer content).",
             "- argmax/argmin mu choose the question to ask; argmax/argmin Delta are best cases only, "
             "since the model, not the asker, draws the answer.", ""]
    sums = {}
    for name in ("CM", "WF"):
        if (RES / name / "metadata.json").is_file():
            txt, sums[name] = persona_section(name)
            parts.append(txt)
    if len(sums) == 2:
        m = sums["CM"].merge(sums["WF"], on="variable", suffixes=("_cm", "_wf"))
        m = m[~m.is_pole_item_cm]
        rho = m[["expected_delta_cm", "expected_delta_wf"]].corr(method="spearman").iloc[0, 1]
        rr = m[["range_cm", "range_wf"]].corr(method="spearman").iloc[0, 1]
        same = (np.sign(m.expected_delta_cm) == np.sign(m.expected_delta_wf)).mean()
        conv = ((m.expected_delta_cm < 0) & (m.expected_delta_wf > 0)).sum()
        div = ((m.expected_delta_cm > 0) & (m.expected_delta_wf < 0)).sum()
        same_ext = (m.answer_plus_cm == m.answer_plus_wf).mean()
        parts += ["## CM vs WF (shared non-pole items)", "",
                  f"- {len(m)} shared non-pole items.",
                  f"- Spearman(mu_CM, mu_WF) = {rho:.3f}; Spearman(range_CM, range_WF) = {rr:.3f}.",
                  f"- Same sign of mu in both personas: {same:.2f}.",
                  f"- Expected convergence items (mu_CM<0, mu_WF>0; CM starts above WF): {conv}; "
                  f"expected divergence items (mu_CM>0, mu_WF<0): {div}.",
                  f"- Same maximizing answer (argmax Delta) in both personas: {same_ext:.2f}.", "",
                  "Since CM is right of WF in J, convergence/divergence here refers to the expected one-step "
                  "displacement only; it says nothing about multi-step accumulation.", ""]
    if a.compare_parallel:
        for name in ("CM", "WF"):
            pf = a.compare_parallel / name / "response_level.csv"
            if pf.is_file() and (RES / name / "response_level.csv").is_file():
                s1 = pd.read_csv(RES / name / "response_level.csv").set_index(["variable", "answer"])
                s2 = pd.read_csv(pf).set_index(["variable", "answer"])
                s2 = s2.loc[s1.index]
                diff = float((s1.I_after - s2.I_after).abs().max())
                pdiff = float((s1.conditional_probability - s2.conditional_probability).abs().max())
                parts += [f"## Serial vs parallel ({name})", "",
                          f"{len(s1)} rows; max |I_after difference| = {diff:.2e}; "
                          f"max |P difference| = {pdiff:.2e}.", ""]
    if a.compare_module and (a.compare_module / "response_level.csv").is_file():
        ref = pd.read_csv(RES / "CM" / "response_level.csv").set_index(["variable", "answer"])
        mod = pd.read_csv(a.compare_module / "response_level.csv").set_index(["variable", "answer"])
        mod = mod.loc[ref.index]
        ms = pd.read_csv(a.compare_module / "variable_summary.csv").set_index("variable")
        rs = pd.read_csv(RES / "CM" / "variable_summary.csv").set_index("variable").loc[ms.index]
        parts += ["## optimizer.one_step_geometry vs reference (CM)", "",
                  f"{len(mod)} rows; max |I_after diff| = {float((ref.I_after - mod.I_after).abs().max()):.2e}; "
                  f"max |P diff| = {float((ref.conditional_probability - mod.conditional_probability).abs().max()):.2e}; "
                  f"max |mu diff| = {float((rs.expected_delta - ms.expected_delta).abs().max()):.2e}.", ""]
    parts += ["## Validation of implementations", "",
              "Serial vs parallel, `optimizer.one_step_geometry` vs this reference, and the incremental",
              "native evaluator vs the per-state path (bit-identical on all pairs): see `ONE_STEP_FINDINGS.md`.", ""]
    (HERE / "ONE_STEP_REPORT.md").write_text("\n".join(parts))
    print("\n".join(parts))


if __name__ == "__main__":
    main()
