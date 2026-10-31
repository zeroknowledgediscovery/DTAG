# DTAG directional item decomposition (exploratory)

This analysis tests which **selected questions** accompany index displacement, using only completed, six-baseline-question calibrated DTAG human trajectories. It uses the exact current schemas from `human_study/scripts/export_dtag_analysis_data.py`: `sessions.csv`, `steps.csv`, `questions.csv`, `assignments.csv`.

## Run

Copy `analyze_item_directional_contributions.py` into `human_study/scripts/` in the DTAG checkout, then run from the repository root:

```bash
python3 human_study/scripts/analyze_item_directional_contributions.py \
  --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
  --gss-map maps/gss/gss_2024_map.csv \
  --out "$HOME/private/dtag-item-analysis-2026-10-30"
```

The `--out` directory must not exist and must be **outside the public repo**. The default requires exactly 71 complete calibrated sessions. For a future or different approved analysis use `--expect-complete N` to override the count. No GCS/Firestore access or LLM inference is performed.

Run the bundled test with `python3 -m unittest test_analyze_item_directional_contributions.py` if both files are together. The test uses synthetic examples only.

## Outputs (private)

- `summary_PRIVATE.json`: group sizes and exact permutation tests.
- `question_categories_PRIVATE.csv`: selected-question category by arm, initial position and final outcome, with signed and positive/negative directional increments.
- `target_questions_PRIVATE.csv`: selected survey variable, count, and observed contribution from the entire question step.
- `mapped_answers_PRIVATE.csv`: survey variable *and accepted native answer value*, plus the observed change *associated* with that mapping. Multiple mappings can refer to the same step, so this file must **not** be summed to attribute index movement.

### The proposed substantive test

Among Left-push participants, compare initially-Right (expected 4) with initially-Left (expected 17) on two participant-level metrics:

1. Fraction of **positive leftward increments** that occurred following spending/program questions. Primary exploratory signal for the proposed ideological-spending explanation.
2. Fraction of selected questions that concern spending/programs. Distinguishes selection/exposure from response-associated displacement.

`spending_program` is predeclared as GSS `nat*` national-spending variables, or question-map text matching spending, welfare, Social Security, government programs/assistance, Medicare, Medicaid, food stamps, or unemployment benefits. The classification uses **selected target question**, not whichever variables the LLM happened to extract from a free-text answer. Use `mapped_answers_PRIVATE.csv` separately to inspect whether spending-related answers are actually supportive of programs.

Both metrics receive an exact label-permutation test within Left push (4 vs 17 at current sample size). The test conditions on a nonrandomized baseline grouping, so its p-value is exploratory rather than a causal effect. Because there are only four initially-Right Left-push participants, interpretation must be cautious.

### Additivity and limits

The recorded per-step increment is exactly `I(after) - I(before)`. Summing it over all 20 questions reconstructs each observed baseline-to-endpoint displacement. This is an **ordered observed trajectory decomposition**. When one answer maps to several survey items, the LSM index update is joint: the CSVs do not contain separate counterfactual incremental updates for each mapped variable. Consequently this analysis does **not** claim unique per-mapped-variable or causal item contributions. A true conditional attribution would require replaying the model with alternative subsets/orderings of mapped assignments.

The script refuses mismatched step/question chains, incomplete trajectories, inconsistent endpoint indices, and mixed zero-calibration cohorts. It does not export session IDs, Prolific IDs, free-text responses, or per-participant trajectories. The aggregate output is still **private** because some cells have very small sample sizes.
