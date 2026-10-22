# Integrated DTAG: adaptive questions, question identities, and order effects

**Branch:** `experiment-integrated-10q`. This directory is self-contained
for the three connected native GSS 2024 analyses. The integrated workflow is
not hooked to GitHub Actions, and no fresh full native experiment was launched
as part of this archival/manuscript revision.

## Run a small native test

From the repository root, after installing the project requirements and native
bindings/model per the root README:

```bash
git fetch origin
git switch experiment-integrated-10q
python experiments/persona_push/run.py --steps 3 --reps 2 --workers 2 \
  --out experiments/persona_push/runs/test_q3_r2
```

Two principal parameters are `--steps` (>=3; need four distinct
permutations) and `--reps` (>=2, independently repeated for *each*
policy and *each* fixed order). Full historical-scale run:

```bash
python experiments/persona_push/run.py --steps 10 --reps 40 --workers 4
```

Stages of `run.py`: (1) select adaptive right, left, neutral, and
random question sequences from fixed pinned personas, sampling native
conditional answers, (2) freeze 18 distinct source-specific item sets
from the first replica and replay original, reversed and two shuffled
orders with matched question-specific uniform variates, (3) optimize a
single global categorical item permutation across the 18 heatmaps and
write three native PGFPlots figure sources plus plot CSV tables.

No CI job is requested. The script runs locally in the foreground;
failure of an individual stage terminates the process with a nonzero
status. The `--figures-only` flag regenerates the same figure products
from an existing run directory without native simulation.

Native path dependencies:
`scripts/dtag_persona_push_study.py`,
`scripts/dtag_fixed_10q_order_test.py`,
`optimizer/dtag_bridge.py`, the native model cache, and
`optimizer/personas/gss2024_spectrum.yaml`.

## Recover a run after a post-simulation plotting error

In a 3-question/2-repeat smoke run, all 144 native order-replay evaluations
may finish before the standalone order-figure generator fails with
`ModuleNotFoundError: No module named 'scripts.dtag_persona_push_study'`.
The import is fixed; **the native results were already saved and do not
need to be recomputed.**

From the repository root, after pulling the updated
`experiment-integrated-10q` branch:

```bash
python experiments/persona_push/run.py \
  --steps 3 --reps 2 \
  --out experiments/persona_push/runs/test_q3_r2 \
  --resume
```

This verifies the 144 saved endpoints and all 432 saved question draws,
regenerates `order/fixed_10q_order_effects.{pdf,png}`, all order-summary
CSV tables, and the three integrated PGFPlots sources under `figures/`.
It creates `order/figure_recovery.json` with checksums and a statement
that **no native simulation was rerun**.

For just the three integrated PGFPlots figures, `--figures-only` remains
available. The standalone order script also supports `--finalize-only`
when called with the saved `--sets` and `--out` paths.

## Archived actual 10q/40r data

- `data/historical_local_20261021/`: the **full local adaptive experiment**
  (`trajectories.csv`, `trajectory_ci.csv`, `endpoints.csv`,
  `versus_random.csv`, `question_counts.csv`, `manifest.json`).
  Contains 960 complete 10-question trajectories.
- `data/historical_order_20261021/CI_results.zip.b64.txt`: a
  byte-preserving base64 representation of the **complete original CI artifact**
  from [Actions run 39709039976](https://github.com/zeroknowledgediscovery/DTAG/actions/runs/39709039976):
  2,880 native ten-question replays, `run_endpoints.csv`, individual
  `question_draws.csv`, the fixed orders, contrasts, manifest, plots, and
  native cache. It is stored in this form because GitHub's text-content
  connector cannot accept binary ZIP uploads. Decode using the helper:
- `data/figures/`: all 24 historical adaptive trajectory CSVs,
  all 18 historical heatmap CSVs (40x10 each), one globally
  shared 228-item lookup (88 used in displayed policies), plus three
  figure-input `.tex` files; these are archived historical outputs,
  not mock values.

To unpack both native historical runs without repeating them:

```bash
python experiments/persona_push/archive_historical.py --plot
```

The recovered data live under
`experiments/persona_push/runs/historical_q10_r40/`, including the
original ZIP. `--plot` additionally reoptimizes the visual index and
generates a fresh set of PGFPlot inputs in that run's `figures/` folder.
This may yield an equally valid *different* approximate seriation from
the frozen archived `data/figures/` question-index ordering.

## Five publication figures (seven PGFPlots sheets)

The manuscript `tex/main.tex` includes `NATIVE_RESULTS_SECTION.tex`.
The figures are *native* PGFPlots with versioned external CSV data,
regenerated directly from archived 10-question, 40-repetition simulations:

1. `fig1_endpoints_pgfplots.tex`: six-persona policy endpoints, 95% bootstrap whiskers, black/pastel point markers.
2. `fig2_trajectories_pgfplots.tex`: six panels of mean response trajectories with 95% pointwise confidence bands.
3. `fig3a_heatmaps_pgfplots.tex` and `fig3b_heatmaps_pgfplots.tex`: all 18 globally optimized categorical heatmaps, each square; split into two legible 3×3 sheets rather than 18 tiny strips.
4. `fig4a_order_effects_pgfplots.tex` and `fig4b_order_effects_pgfplots.tex`: the exact *Python-analysis presentation* of the six-persona × three-source-policy paired order effects, with reverse/shuffle1/shuffle2 mean contrasts and 95% paired bootstrap whiskers. These are not bar plots.
5. `fig5_sign_reversal_probabilities_pgfplots.tex`: probability of reversing final ideological sign or direction of net movement, with 95% bootstrap CIs clustered by independent repetition index (the three alternative orders share one baseline realization).

Create both PDFs from the repo's **archived original datasets only**, without
loading or sampling a native LSM:

```bash
python experiments/persona_push/archive_historical.py --plot
cd tex
latexmk -pdf -interaction=nonstopmode -halt-on-error figures_preview.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

For new native runs, `run.py --steps N --reps R` invokes both
`plot_pgf.py` (index optimization and analytical plot tables) and
`publication_pgfplots.py` (all five final figure designs).
The figures in `experiments/persona_push/data/figures/` are the frozen
historical *outputs* generated using N=10 and R=40.
The archived historical order runs and local adaptive runs come from
different native execution environments; compare effects within their
respective experiments, not absolute initial index values across environments.

## Interpretation and cautions

The original adaptive study and original CI replay are *different native
execution environments*. Their recorded semantic-map, persona and pole
hashes agree but their starting indices differ; the native model binary
was not hashed in both historical manifests. Do not equate absolute
numerical index values across the two runs until model hash/parity is
verified. All within-study and paired-replay comparisons are internally
defined.

The fixed-order comparison demonstrates pathwise outcomes, including
sign reversals under matched random uniform variates, not automatically
different marginal endpoint laws, and not a change in real human beliefs.
The all-pairs item-index objective is only a visualization seriation,
not a distance between question meanings.

Historical sign-reversal counts: right-derived 131/720 movement reversals
and 43/720 final-index reversals; left-derived 21/720 and 4/720;
neutral-derived 0/720 for both. The three alternative permutations share
the same baseline replicate, so comparisons are not independent.

## Checks performed on this branch

The integrated drivers passed Python syntax checks and an end-to-end
`--figures-only` smoke using the existing short native dataset as a
fixture. All three PGFPlots templates compiled in LaTeX when supplied
with matrix-complete fixture CSVs, and the modified IEEEtran manuscript
compiled to an 8-page PDF using the fixture plot tables. The entire
new native 3-question/2-repetition or 10-question/40-repetition pipeline
was **not rerun**.
