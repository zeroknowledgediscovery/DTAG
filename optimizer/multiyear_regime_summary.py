"""Inventory existing, independently validated DTAG trajectory experiments across GSS waves.

This is a descriptive reproducibility report; it does not generate, rank, select,
or export question sequences by political effect.

Run from the DTAG repository root:
    python -m optimizer.multiyear_regime_summary \
        --runs-root outputs/optimizer --out outputs/optimizer/multiyear_audit \
        --years 2016 2018 2024 --target-per-cell 3
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from .four_way_audit import analyze

CATEGORIES = ("++", "+-", "-+", "--")
LABEL_TO_CATEGORY = {
    "positive_translation": "++",
    "divergence": "+-",
    "convergence": "-+",
    "negative_translation": "--",
}


def get_year(folder):
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    key = str((data.get("model") or {}).get("key") or "")
    for year in (2016, 2018, 2024):
        if key == f"gss/gss_{year}":
            return year
    return None


def inventory(runs_root, out, years=(2016, 2018, 2024), target_per_cell=3,
              bootstrap=2000, neutral_band=.005):
    root, output = Path(runs_root).resolve(), Path(out).resolve()
    if target_per_cell < 1:
        raise ValueError("target_per_cell must be at least 1")
    if not root.exists():
        raise FileNotFoundError(root)
    folders = sorted(p.parent for p in root.rglob("validation_trajectories.npz")
                     if output not in p.parents and p.parent != output)
    results = []
    for i, folder in enumerate(folders):
        year = get_year(folder)
        if year not in years:
            continue
        result = analyze(folder, seed=20261016 + i, nboot=bootstrap, band=neutral_band)
        groups = result.get("groups", {})
        pos = (groups.get("positive") or {}).get("raw_change_ci") or {}
        neg = (groups.get("negative") or {}).get("raw_change_ci") or {}
        category = LABEL_TO_CATEGORY.get(result.get("observed_regime"))
        # Evidence quality (0-10) measures completeness, NOT directional strength.
        # Independent states matter more than repeated answer draws.
        positive = groups.get("positive") or {}
        negative = groups.get("negative") or {}
        state_factor = min(1.0, positive.get("n_states", 0) / 50.0,
                           negative.get("n_states", 0) / 50.0)
        draws_factor = min(1.0,
                           (positive.get("n_draws", 0) / max(1, positive.get("n_states", 0))) / 20.0,
                           (negative.get("n_draws", 0) / max(1, negative.get("n_states", 0))) / 20.0)
        mapped = (folder / "question_set_detail.csv").is_file()
        quality = round(10 * (0.5 * state_factor + 0.3 * draws_factor +
                              0.1 + 0.1 * int(mapped)), 1)
        # Do not label an uncertain result as a supported directional finding.
        confirmed = result["status"] == "supported_by_state_bootstrap"
        results.append({
            "year": year,
            "source": str(folder.relative_to(root)),
            "evidence_quality_0_to_10": quality,
            "category_observed": category,
            "confirmed": confirmed,
            "positive_raw_mean": pos.get("mean"),
            "positive_ci_low": pos.get("low"),
            "positive_ci_high": pos.get("high"),
            "negative_raw_mean": neg.get("mean"),
            "negative_ci_low": neg.get("low"),
            "negative_ci_high": neg.get("high"),
            "distinct_starting_states": result.get("n_states"),
            "trajectories": result.get("n_trajectories"),
        })
    count = Counter((r["year"], r["category_observed"]) for r in results if r["confirmed"])
    matrix = []
    for year in years:
        for category in CATEGORIES:
            n = count[(year, category)]
            matrix.append({"year": year, "category": category,
                           "confirmed_runs": n, "target": target_per_cell,
                           "gap": max(0, target_per_cell - n)})
    output.mkdir(parents=True, exist_ok=True)
    def csv_write(name, rows):
        with (output / name).open("w", encoding="utf-8", newline="") as file:
            if rows:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    csv_write("observed_runs.csv", results)
    csv_write("coverage_matrix.csv", matrix)
    report = {
        "scope": "descriptive model-index changes for existing validation runs",
        "years": list(years), "target_per_cell": target_per_cell,
        "method": "distinct-starting-state clustered bootstrap confidence intervals",
        "warning": "Not evidence of changes to real political attitudes; no sequences were generated or selected.",
        "quality_definition": "0-10 = 5 points for >=50 distinct starting states per group, 3 for >=20 draws per state, 1 for model manifest, 1 for mapped-question detail. Not an effectiveness score.",
        "runs": results, "coverage": matrix,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2))
    lines = [
        "# Cross-wave DTAG four-regime coverage", "",
        "Inventory of *existing* validation trajectories. No question sequences",
        "are generated, selected, or ranked. The 0-10 evidence-quality score",
        "measures sample/provenance completeness, NOT magnitude of political movement.",
        "Category signs refer to the",
        "raw inferred ideology-index changes (positive-start, negative-start).",
        "Only runs with both state-bootstrap intervals excluding zero count as",
        "confirmed. A target of 3 per cell is a reporting benchmark,",
        "not an optimization objective or guarantee.", "",
        "| GSS year | ++ | +- | -+ | -- |",
        "|---|---:|---:|---:|---:|",
    ]
    for year in years:
        lines.append("| " + str(year) + " | " +
                     " | ".join(str(count[(year, cat)]) for cat in CATEGORIES) + " |")
    lines += ["", f"Target: at least {target_per_cell} independent validated inputs per year/regime.",
              "See coverage_matrix.csv for gaps and observed_runs.csv for evidence.",
              "The same candidate under multiple run directories may appear more than",
              "once; this is a run inventory, not a count of unique question sets.",
              "LLM decoding and question mapping must be compared across runs before",
              "drawing between-year or causal conclusions.", ""]
    (output / "README.md").write_text("\n".join(lines))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default="outputs/optimizer")
    parser.add_argument("--out", default="outputs/optimizer/multiyear_audit")
    parser.add_argument("--years", nargs="+", type=int, default=[2016, 2018, 2024])
    parser.add_argument("--target-per-cell", type=int, default=3)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--neutral-band", type=float, default=.005)
    args = parser.parse_args(argv)
    result = inventory(args.runs_root, args.out, years=tuple(args.years),
                       target_per_cell=args.target_per_cell,
                       bootstrap=args.bootstrap, neutral_band=args.neutral_band)
    for row in result["coverage"]:
        print(f"{row['year']} {row['category']}: {row['confirmed_runs']} confirmed; "
              f"gap={row['gap']}")
    print(f"Saved inventory to {args.out}")


if __name__ == "__main__":
    main()
