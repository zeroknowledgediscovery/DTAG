# GSS 2016 / 2018 / 2024: local-first four-regime results inventory

**Purpose:** a reproducible descriptive inventory of fixed-model ideology-index changes
from independently defined, pre-existing DTAG question-sequence validations.
This tool does **not** search for political questions, optimize directional effects,
select top-performing sequences, or create new sequences to influence respondents.
Inferred model-index changes are not evidence of changes in human political attitudes.

## Scope and sign convention

For each observed simulation, define raw delta = I_end - I_start, and group
by the sign of the ACTUAL I_start after state initialization.

| Code | Positive-start group | Negative-start group | Descriptive regime |
|---|---|---|---|
| ++ | raw delta > 0 | raw delta > 0 | Both indexes increase |
| +- | raw delta > 0 | raw delta < 0 | Divergence |
| -+ | raw delta < 0 | raw delta > 0 | Convergence in direction; inspect overshoot |
| -- | raw delta < 0 | raw delta < 0 | Both indexes decrease |

The existing audit in optimizer/four_way_audit.py clusters repeated answer draws
by distinct starting state and bootstraps state means. A regime is counted as
**confirmed** only if both state-bootstrap 95% confidence intervals exclude zero
in the corresponding direction. A negative-start outward-signed change must be
NEGATED to obtain its raw change.

## Local invocation

From the DTAG repository root, on branch dev:

    git switch dev
    git pull --ff-only origin dev
    pip install -r requirements.txt

    python -m optimizer.multiyear_regime_summary \
        --runs-root outputs/optimizer \
        --out outputs/optimizer/multiyear_audit \
        --years 2016 2018 2024 \
        --target-per-cell 3

The script recursively finds completed validation_trajectories.npz files, reads
each adjacent manifest.json to identify the GSS model year, and uses the
already stored initial ideology, trajectory, and state ID arrays. It does not
run the native model or make LLM calls and can be rerun offline if dependencies
are installed.

Outputs:

- multiyear_audit/README.md: readable 3-year by 4-regime coverage matrix.
- multiyear_audit/coverage_matrix.csv: confirmed counts and gaps to the
  reporting target of 3 for each of 12 year/regime cells.
- multiyear_audit/observed_runs.csv: one row per evaluated saved run, with
  observed sign regime, group raw changes, intervals, states, trajectories,
  and 0-to-10 **evidence quality**, not persuasion efficacy.
- multiyear_audit/summary.json: full structured results and methodology.

**Evidence-quality scale (0–10), independent of directional outcomes:**

- Up to 5 points: at least 50 distinct initialized states per starting-index group.
- Up to 3 points: at least 20 response draws per state in each group.
- 1 point: model/year manifest available.
- 1 point: mapped-question detail CSV available.

Intermediate state/draw counts receive proportional partial credit.
The score does not measure the size, sign, t-statistic, or political usefulness
of an effect. It is not a criterion for selecting or ranking question wording.

The input files themselves remain in their original run directories, which
include provenance and mappings. The tool intentionally does not copy or
export question text into a sign-coded collection.

## Inputs and reproducibility

A previously run validation directory should contain:

    manifest.json
    validation_trajectories.npz
    validation.json
    question_set.csv
    question_set_detail.csv
    starting_states.jsonl

The trajectory file is the required analysis input; manifest.json must record
model.key = gss/gss_2016, gss/gss_2018, or gss/gss_2024.
Some older runs lack the full set of files; this is reflected in provenance
quality. The stored native model and exact question mapping affect comparability.

Current GSS 2024 simulations already saved under outputs/optimizer can be
included in the summary if present. GSS 2016 and 2018 require separate
validations, wave-specific semantic maps/poles, and audited persona decode;
do not simply relabel a GSS 2024 result with another year.

The target_per_cell parameter is a **completeness benchmark**, not a promise that
a given sign regime is represented or an instruction to search for targeted
political effects. Empty or weakly supported cells remain visible as gaps.
This is especially relevant for non-representative CM/WF source personas.

## Future MCC preparation

The inventory is local-first and requires no cluster integration. The
corresponding native simulations, if independently specified for scientific
evaluation, should later be scheduled as separate per-year/per-sequence
batch jobs with resource limits and immutable input manifests. Keep the
summary step as an offline postprocessing job; avoid concurrent writes to
the same output folder and check that LLM/persona caches are deterministic.

Do not claim state-level independent sampling if the same starting state is
repeated across many trajectories; only distinct starting-state clusters
count for confidence intervals.

Test locally:

    pytest -q optimizer/tests

For the original 2024 four-way descriptive catalog, see:
optimizer/four_way_catalog.yaml and optimizer/README.md.
