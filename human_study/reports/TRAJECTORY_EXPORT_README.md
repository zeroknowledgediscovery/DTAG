# DTAG private trajectory preservation (restored 2026-10-30 cohort)

**Purpose.** Retain machine-readable model-index trajectories for future DTAG
post-processing without exposing participants' sensitive inferred survey
phenotypes in this **public** repository.

The immutable original `final.json` objects remain the scientific sources of
truth in the access-controlled research bucket. A trajectory export is a
derived, reproducible research artifact, not a substitute for those originals.

## Generate a private, postprocessable snapshot

First ensure that the repaired `final.json` is included in the refreshed
private analysis export (`~/private/dtag-analysis-2026-10-30-restored`).
Then, from the DTAG repository root:

```bash
git fetch origin experiment/prolific-human-study
git restore --source=origin/experiment/prolific-human-study --worktree -- \
    human_study/scripts/export_private_trajectories.py

python3 human_study/scripts/export_private_trajectories.py \
    --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
    --out "$HOME/private/dtag-trajectories-2026-10-30-restored" \
    --expect-complete 102
```

The `--expect-complete 102` assertion refers to the investigator-reported
**expected** total after recovering the missing original-study participant
(71 calibrated + 31 zero-calibration Right). It is a safeguard, not a hardcoded
protocol size. Remove/adjust the flag for later live cohorts.

The output folder must be new and **outside** the public Git checkout. Files
have private permissions (0700 directory, 0600 files). It contains:

| Private artifact | Meaning |
|---|---|
| `trajectories_wide_PRIVATE.csv` | One row/session; `i00`–`i20` (index), `d00`–`d20` (change from baseline), arm, study, cohort, Q4 flag, final outcome |
| `trajectories_long_PRIVATE.csv` | One row/actually observed step (0–20); index, delta, model-projected and observed step deltas, accepted-assignment count |
| `trajectories_group_step_PRIVATE.csv` | Aggregate group-step counts and means by protocol, study, recruitment cohort, arm, and initial index sign |
| `trajectory_manifest_PRIVATE.json` | Export counts, source-manifest checksum, and SHA-256 of each derived CSV |

Each participant is represented by existing HMAC pseudonyms
(`session_uid`, `participant_uid`). These do **not** make the individual
trajectories safe for public posting. Prolific IDs, respondent prose, and raw
survey-variable assignments are intentionally excluded.

`initial_ideology` is computed only for **six-question calibrated**
participants. Zero-calibration indexes are labeled
`empty_state_not_human_phenotype`: Democratic/Republican recruitment must
not be conflated with directly measured baseline ideology.

By default, the export includes verified **complete** 20/20 trajectories in
all production policies, including Neutral, Random and zero-calibration Right.
Use `--include-partial` to retain additional actually observed steps for
incomplete sessions (missing future steps are blank); never impute them.

## Preserve a durable copy

Use the configured **private** research GCS bucket for the derived snapshot.
Verify IAM and retention before upload; do not use a public `git-gcs` bucket.

```bash
gcloud storage buckets describe gs://pkcsaas-01-dtag-study-data \
    --format="json(iamConfiguration,retentionPolicy)"

gcloud storage cp --recursive \
    "$HOME/private/dtag-trajectories-2026-10-30-restored" \
    "gs://pkcsaas-01-dtag-study-data/private-analysis/"
```

This preserves the entire directory under a versioned name in the private
bucket, including hashes and cohort metadata. Do not upload the pseudonymization
key or private crosswalk, and **never `git add` these trajectories** to the
public DTAG repository. Treat subsequent runs as new versioned snapshots rather
than replacing historical analysis data.

## Q4 baseline-relative classifier

For calibrated initially Left-leaning participants assigned Right push,
`q4_resistance_flag` records the criterion
`(I4-I0)/4 <= 0` (with numerical tolerance `1e-10`).
`endpoint_correct_resistance` requires non-rightward cumulative displacement
at Q20. These columns permit independent recomputation of the published
[Q4 resistance table](q4_resistance_2026-10-30.md).

**Provenance.** The actual participant-level files must be generated on the
investigator's workstation, where the private analysis export is stored.
The repository contains only their generation code and aggregate
investigator-reported Q4 findings; it does not contain the private trajectories.
