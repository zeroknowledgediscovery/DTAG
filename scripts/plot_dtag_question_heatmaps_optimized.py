#!/usr/bin/env python3
"""Optimize ONE global question-index permutation for 18 DTAG heatmaps.

    python scripts/plot_dtag_question_heatmaps_optimized.py \
        --input outputs/dtag_persona_push/main/trajectories.csv \
        --out outputs/dtag_persona_push/optimized_heatmaps \
        --steps 10 --reps 40 --objective adjacent

Produces globally indexed 40x10 matrices for six personas and three policies
(right, left, neutral); random is not plotted. The same question has the same
color in every panel. Random-only questions are indexed, but go at the end.

'--objective adjacent' minimizes total vertical |index difference| between
consecutive run rows, at the same question position, summed over all panels.
'--objective allpairs' uses all 40-choose-2 run pairs at the same question
position: more principled if run numbers are arbitrary.

Both are *display-only seriations*, not a measured semantic distance between
questions. Greedy swaps seek a local optimum; global optimality isn't claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
import numpy as np
import pandas as pd

POLICIES = ("right", "left", "neutral")
PERSONAS = (
    "cm_rural_alabama", "wf_new_york_city",
    "religious_conservative_woman_texas", "secular_liberal_man_seattle",
    "hispanic_catholic_man_arizona", "black_churchgoing_woman_atlanta",
)
TITLES = {"right": "Push right", "left": "Push left", "neutral": "Neutral"}


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, keep_default_na=False, low_memory=False)
    required = {"persona", "policy", "rep", "step", "variable", "question"}
    if not required.issubset(frame):
        raise ValueError(f"Missing input fields: {sorted(required - set(frame))}")
    frame["rep"] = pd.to_numeric(frame["rep"]).astype(int)
    frame["step"] = pd.to_numeric(frame["step"]).astype(int)
    frame["variable"] = frame["variable"].astype(str).str.strip()
    frame = frame[frame["step"] > 0].copy()
    if frame.empty or frame["variable"].eq("").any():
        raise ValueError("No questions or blank/padded question variables")
    return frame


def index_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Frequency-ranked baseline IDs over every policy, including random."""
    freq = (frame.groupby("variable").agg(
        total_uses=("variable", "size"),
        personas=("persona", "nunique"),
        policies=("policy", "nunique"),
    ).reset_index().sort_values(
        ["total_uses", "variable"], ascending=[False, True]
    ).reset_index(drop=True))
    text = (frame[frame["question"].astype(str).str.strip().ne("")]
            .groupby("variable")["question"]
            .agg(lambda s: s.value_counts().index[0])
            .rename("question").reset_index())
    freq = freq.merge(text, on="variable", how="left", validate="one_to_one")
    freq.insert(0, "frequency_index", np.arange(1, len(freq) + 1))
    return freq


def matrices(frame: pd.DataFrame, table: pd.DataFrame, steps: int, reps: int):
    """Return 18 verified matrices using zero-based frequency IDs."""
    ids = dict(zip(table.variable, range(len(table))))
    data = frame[frame["policy"].isin(POLICIES) &
                 frame["persona"].isin(PERSONAS)].copy()
    data["old_id"] = data["variable"].map(ids)
    result = {}
    for persona in PERSONAS:
        for policy in POLICIES:
            chunk = data[(data["persona"] == persona) & (data["policy"] == policy)]
            if len(chunk) != reps * steps:
                raise ValueError(f"{persona} {policy}: {len(chunk)} question rows, "
                                 f"expected {reps*steps}")
            mat = chunk.pivot(index="rep", columns="step", values="old_id")
            mat = mat.reindex(index=range(reps), columns=range(1, steps + 1))
            if mat.isna().any().any():
                raise ValueError(f"Missing, duplicated, or misnumbered run/step: "
                                 f"{persona} {policy}")
            arr = mat.to_numpy(dtype=int)
            if any(len(set(row)) != steps for row in arr):
                raise ValueError(f"Repeated variable within a run: {persona} {policy}")
            result[(persona, policy)] = arr
    return result, data


def affinity(mats: dict, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Construct both exact weighted-minimum-linear-arrangement objectives."""
    adjacent = np.zeros((n, n), dtype=float)
    allpairs = np.zeros_like(adjacent)
    for mat in mats.values():
        for t in range(mat.shape[1]):
            x = mat[:, t]
            np.add.at(adjacent, (x[:-1], x[1:]), 1.)
            cnt = np.bincount(x, minlength=n).astype(float)
            allpairs += np.outer(cnt, cnt)
    adjacent += adjacent.T
    np.fill_diagonal(adjacent, 0.)
    np.fill_diagonal(allpairs, 0.)
    return adjacent, allpairs


def arrangement_cost(order: np.ndarray, graph: np.ndarray) -> float:
    ranks = np.empty(len(order), dtype=int)
    ranks[order] = np.arange(len(order))
    return float(np.sum(np.triu(
        graph * np.abs(ranks[:, None] - ranks[None, :]), 1)))


def greedy_swaps(initial: np.ndarray, graph: np.ndarray, max_swaps: int):
    """Best improving swap with O(n) exact change per candidate swap."""
    order = np.asarray(initial, dtype=int).copy()
    n = len(order)
    pos = np.empty(n, dtype=int)
    pos[order] = np.arange(n)
    cost = arrangement_cost(order, graph)
    count = 0
    for _ in range(max_swaps):
        best_change, bi, bj = -1e-9, -1, -1
        for i in range(n - 1):
            a = order[i]
            for j in range(i+1, n):
                b = order[j]
                d = np.abs(j-pos) - np.abs(i-pos)
                d[a] = d[b] = 0
                change = float((graph[a] - graph[b]) @ d)
                if change < best_change:
                    best_change, bi, bj = change, i, j
        if bi < 0:
            break
        a, b = order[bi], order[bj]
        order[bi], order[bj] = b, a
        pos[a], pos[b] = bj, bi
        cost += best_change
        count += 1
    exact = arrangement_cost(order, graph)
    if not np.isclose(exact, cost, atol=1e-5, rtol=1e-8):
        raise AssertionError(f"Swap cost mismatch: {exact} vs {cost}")
    return order, exact, count


def optimize(mats, lookup, objective, seed=17, max_swaps=20):
    n = len(lookup)
    adjacent, allpairs = affinity(mats, n)
    full_graph = adjacent if objective == "adjacent" else allpairs
    active = np.unique(np.concatenate([m.ravel() for m in mats.values()]))
    inactive = np.setdiff1d(np.arange(n), active, assume_unique=True)
    m = len(active)
    graph = full_graph[np.ix_(active, active)]

    # Multistart from frequency, two low-frequency spectral modes, and RNG.
    starts = [np.arange(m, dtype=int)]
    if m >= 3 and graph.sum() > 0:
        laplacian = np.diag(graph.sum(axis=1)) - graph
        try:
            vals, vecs = np.linalg.eigh(laplacian)
            positive = np.flatnonzero(vals > max(1e-9, vals[-1] * 1e-10))
            for k in positive[:min(2, len(positive))]:
                starts.append(np.lexsort((np.arange(m), vecs[:, k])))
        except np.linalg.LinAlgError:
            pass
    starts.append(np.random.default_rng(seed).permutation(m))
    print(f"Optimizing {m} displayed question IDs ({len(inactive)} excluded-policy IDs).",
          flush=True)
    candidates = []
    for k, ordering in enumerate(starts, 1):
        result = greedy_swaps(ordering, graph, max_swaps=max_swaps)
        candidates.append(result)
        print(f"  start {k}/{len(starts)}: score={result[1]:,.0f}, "
              f"improving swaps={result[2]}", flush=True)
    local_order, _, _ = min(candidates, key=lambda x: x[1])
    order = np.concatenate([active[local_order], inactive])
    if len(np.unique(order)) != n:
        raise AssertionError("Index permutation has duplicates")
    before = np.arange(n, dtype=int)
    report = {
        "objective": objective, "total_unique_questions": n,
        "displayed_unique_questions": m, "excluded_only_questions": len(inactive),
        "panels": 18, "starts": len(starts), "max_swaps": max_swaps,
        "seed": seed,
        "objective_before": arrangement_cost(before, full_graph),
        "objective_after": arrangement_cost(order, full_graph),
        "adjacent_before": arrangement_cost(before, adjacent),
        "adjacent_after": arrangement_cost(order, adjacent),
        "allpairs_before": arrangement_cost(before, allpairs),
        "allpairs_after": arrangement_cost(order, allpairs),
        "note": "Global IDs optimize appearance only; differences between question "
                "indices are not survey-item semantic distances. The adjacent "
                "objective depends on arbitrary run order; allpairs does not.",
    }
    if report["objective_before"] > 0:
        report["fraction_reduced"] = (report["objective_before"] -
                                      report["objective_after"]) / report["objective_before"]
    return order, report, m


def render(mats, order, nactive, out, reps, steps):
    n = len(order)
    pos = np.empty(n, dtype=int)
    pos[order] = np.arange(1, n+1)
    cmap = plt.get_cmap("turbo", nactive)
    norm = BoundaryNorm(np.arange(0.5, nactive+1.5), nactive)
    fig, axes = plt.subplots(6, 3, figsize=(12.8, 17.5),
                             sharex=True, sharey=True, constrained_layout=True)
    for i, persona in enumerate(PERSONAS):
        for j, policy in enumerate(POLICIES):
            ax = axes[i, j]
            arr = pos[mats[(persona, policy)]]
            if not np.all((arr >= 1) & (arr <= nactive)):
                raise AssertionError("Plot includes random-only question ID")
            im = ax.imshow(arr, cmap=cmap, norm=norm, aspect="auto",
                           interpolation="nearest", origin="upper")
            if i == 0:
                ax.set_title(TITLES[policy], fontsize=11)
            if j == 0:
                ax.set_ylabel(persona.replace("_", " ") + "\nrun index", fontsize=8)
            if i == len(PERSONAS)-1:
                ax.set_xlabel("Question position", fontsize=10)
            ax.set_xticks(np.arange(steps), np.arange(1, steps+1))
            yy = np.unique(np.linspace(0, reps-1, min(reps, 5), dtype=int))
            ax.set_yticks(yy, yy+1)
            ax.tick_params(length=0, labelsize=8)
    cbar = fig.colorbar(im, ax=axes.ravel().tolist(), shrink=.83, aspect=38)
    cbar.set_label("Global optimized question index (display categories)")
    tickstep = max(1, int(np.ceil(nactive / 10)))
    cbar.set_ticks(np.arange(1, nactive+1, tickstep))
    fig.suptitle("DTAG | Global question-index seriation | 6 personas x 3 policies",
                 fontsize=14)
    pdf = out / "question_heatmaps_optimized_18panel.pdf"
    png = out / "question_heatmaps_optimized_18panel.png"
    fig.savefig(pdf, bbox_inches="tight")
    fig.savefig(png, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return pdf, png


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        default=Path("outputs/dtag_persona_push/main/trajectories.csv"))
    parser.add_argument("--out", type=Path,
                        default=Path("outputs/dtag_persona_push/optimized_heatmaps"))
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--reps", type=int, default=40)
    parser.add_argument("--objective", choices=("adjacent", "allpairs"),
                        default="adjacent")
    parser.add_argument("--max-swaps", type=int, default=20)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    if args.steps < 1 or args.reps < 2 or args.max_swaps < 0:
        parser.error("steps>=1, reps>=2 and max-swaps>=0 are required")
    args.out.mkdir(parents=True, exist_ok=True)
    data = read_csv(args.input)
    lookup = index_table(data)
    mats, plotted_data = matrices(data, lookup, args.steps, args.reps)
    order, report, active = optimize(mats, lookup, args.objective,
                                     seed=args.seed, max_swaps=args.max_swaps)
    indexed = lookup.iloc[order].copy().reset_index(drop=True)
    indexed.insert(0, "question_index", np.arange(1, len(indexed)+1))
    indexed.to_csv(args.out / "question_index_optimized.csv", index=False)
    indexed.to_csv(args.out / "question_index.csv", index=False)
    positions = dict(zip(indexed.variable, indexed.question_index))
    plotted_data["question_index"] = plotted_data["variable"].map(positions)
    plotted_data.sort_values(["persona", "policy", "rep", "step"]).to_csv(
        args.out / "indexed_question_sequences.csv", index=False)
    (args.out / "optimization_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pdf, png = render(mats, order, active, args.out, args.reps, args.steps)
    print(f"Score {report['objective_before']:,.0f} -> "
          f"{report['objective_after']:,.0f} "
          f"({report.get('fraction_reduced', 0):.1%} reduction)")
    print(f"Wrote {pdf} and {png}; question_index.csv; optimization_report.json")


if __name__ == "__main__":
    main()
