# NHB explanatory analyses: archived calibrated DTAG participants

The analysis is a standalone, reproducible post-processing pass on the restored
**private** human-study export. No new recruitment, LSM inference, browser
session, API calls, or downloads are needed.

**Implementation:** `human_study/scripts/analyze_nhb_explanations.py`
**Synthetic regression tests:** `human_study/tests/test_analyze_nhb_explanations.py`
**Public, publication-oriented aggregate directory:**
`tex/Figures/nhb_explanatory/`
**Detailed investigator-only outputs:** choose a new path beneath
`$HOME/private/`. Never commit them.

## Run (from DTAG repository root)

```bash
git switch experiment/prolific-human-study
git pull --ff-only origin experiment/prolific-human-study

python3 -m pytest -q human_study/tests/test_analyze_nhb_explanations.py

python3 human_study/scripts/analyze_nhb_explanations.py \
  --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
  --gss-map maps/gss/gss_2024_map.csv \
  --private-out "$HOME/private/dtag-nhb-explanations-2026-10-31" \
  --bootstrap 2000 --seed 20261031
```

The private output directory must **not exist** when run. The public output
directory is fixed to the repository's `tex/Figures/nhb_explanatory/`.
This is deliberate: it prevents the detailed small-cell tables from being
accidentally written to an arbitrary public path. Use a distinct new private
directory for a rerun, or review/delete a previous local private run first.

Expected console summary: 71 complete calibrated sessions, 1,420 question
events, Q4 TP=17, FP=2, FN=0, TN=10; flagged initially Left Right-push
n=19, unflagged initially Left Right-push n=10, initially Right
Right-push n=9. Any mismatch aborts.

## Three complementary analyses

### 1. Resistance-associated question selection and displacement

The Q4 split is fixed at nonpositive baseline-relative index movement after
four Right-push answers **only among 29 initially Left participants**:
19 flagged versus 10 unflagged. The nine initially Right Right-push
participants are shown separately. The script reports for each subgroup:

- Q1–Q4, Q5–Q20, and all-20 signed movement, with participant-bootstrap
  intervals (not independent out-of-sample confidence intervals).
- Distribution of selected question topics; event counts, participant
  coverage, exposure share, positive and **net** signed displacement.
- High-frequency individual native target variables, with low-frequency
  cells suppressed from the public output.
- Full trajectories for a follow-on resistance-pattern figure.

A Q4-selected population is **not** a valid control for a causal study of
resistance, and the report should avoid calling it a stable individual trait.

### 2. LSM prediction versus observed human increment

The export contains `predicted_target_only_delta`, a prediction for the
question's target variable, and `observed_step_delta`, the change after
the respondent's **accepted mapping(s)**. The latter can be a multi-variable
joint update. The script checks observed delta against consecutive archived
indices, and reports:

- Number of steps with recorded predictions, including prediction scope.
- Signed prediction minus observed error, mean absolute error, and sign
  agreement for **single accepted assignment** separately from all
  assignments.
- Private by-wave/by-scope diagnostics to detect implementation changes.
- Public five-bin, event-weighted predicted-versus-observed summaries
  restricted to single-assignment steps, with a participant-cluster
  bootstrap for interval estimates.

Interpret differences as prediction/observation discrepancies under this
implementation, **not** as randomized estimates of persuasion or model
calibration against identical estimands.

### 3. Associated native answer categories

The private table records selected question target, accepted
`mapped_variable`, native `native_value`, n sessions, n associated
events, and positive/net changes. If the interface mapped one free-text
response to several variables, the same question-event change appears
in several associations: **never sum these as distinct item contributions**.

To publish reviewed native categories, first inspect the PRIVATE table.
Make your own answer whitelist CSV outside the repo:

```text
mapped_variable,native_value,public_label
```

A blank template is provided in
`human_study/config/nhb_answer_allowlist.example.csv`.
Append explicitly approved pairs with short human-readable labels. Then
rerun the analysis to a **different new private output path**:

```bash
python3 human_study/scripts/analyze_nhb_explanations.py \
  --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
  --private-out "$HOME/private/dtag-nhb-explanations-answers-2026-10-31" \
  --answer-allowlist "$HOME/private/nhb_answer_allowlist.csv"
```

Only reviewed categories that appear in >=5 participants and >=8 events
in the pooled Left or pooled Right policy are published. Original native
values and free-text are never written to public output. If no allowlist
is provided, the public answer-category CSV contains only its column
header. The private category file is never eligible for commit.

## Public output contract

See `tex/Figures/nhb_explanatory/README.md` for descriptions. The
pipeline writes a consistent set of aggregate files, and a public manifest
with available prediction coverage. Empty CSVs are intentional if the
coverage or privacy threshold is unmet. Values should not be invented to
fill them.

The topic family heuristic has fixed explicit overrides for common
GSS items and keyword matches to the public GSS wording. Review it for
scientific validity before interpreting topic-level differences.

## Safe commit procedure

After the run, **review the aggregate values and header columns**:

```bash
ls -lh tex/Figures/nhb_explanatory/
git status --short
git diff -- tex/Figures/nhb_explanatory/
```

Ensure none of the output contains a local participant UID, original
answer text, Prolific ID, or identifying metadata. This is a required
investigator disclosure review, not an automatic guarantee.

```bash
git add tex/Figures/nhb_explanatory/
git commit -m "Add audited aggregate NHB resistance and explanation results"
git push origin experiment/prolific-human-study
```

**Do not run** `git add -A` without checking for private exports and
never commit anything under `$HOME/private`.

## Connection to dtag_main2.tex

The generated outputs support two potential new main-text or Extended
Data displays:

1. **Q4-conditioned Right-push trajectory**, with the 19 flagged, 10
   unflagged and 9 initially-Right participants shown separately,
   giving the direction and timing of differences;
2. **Predicted-versus-observed signed displacement**, limited to
   single-assignment human steps with recorded LSM predictions.

A companion table can present the selected topic families and their
net contributions during Q5–Q20. The manuscript should be updated
**after** actual output values have been checked. These scripts do not
alter `dtag_main2.tex`, `humanstudy_new.tex`, or existing Figure 1–4
externalization commands.

## What cannot be settled from the archives alone

The private export gives question targets, accepted native response
categories, joint index updates, and target-only model predictions.
It does **not** reveal the causal effect of asking a question, disentangle
psychological attitude change from selective measurement, or apportion
a multi-variable update among its mapped variables without re-evaluating
the LSM for counterfactual subsets. External validity of the GSS-derived
ideology axis would require held-out human responses or independent
measurements.
