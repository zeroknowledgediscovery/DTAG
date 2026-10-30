# DTAG downstream analysis dataset (PRIVATE)

This document describes the analysis-ready dataset produced by
[`human_study/scripts/export_dtag_analysis_data.py`](../scripts/export_dtag_analysis_data.py).

The exporter builds a **private, reproducible, participant/session-level and
question-level** dataset from the latest all-study audit's private crosswalk and
the actual archived DTAG human responses. It does not use aggregate summary
statistics to manufacture individual-level data.

The exporter itself is versioned in GitHub. **The resulting CSVs, HMAC key,
Prolific PDFs, and protected participant crosswalk must not be committed.**

## Prerequisites

Run the earlier read-only
[`audit_all_dtag_prolific.py`](../scripts/audit_all_dtag_prolific.py)
against GCP and the two private invoices. The audit must have generated:

- `PRIVATE_all_sessions.csv`: each discovered Firestore/GCS session (including
  incomplete sessions);
- `PRIVATE_participant_crosswalk.csv`: the **30 approved** Prolific IDs from
  the two latest payment rosters matched to stored DTAG sessions.

Both are in the *private* audit directory. The exporter loads the original
immutable `final.json` archives from
`gs://pkcsaas-01-dtag-study-data/studies/<study-id>/sessions/<session-id>/`
and, for sessions without a final archive, the actual per-question
`baseline/`, `questions/`, `attention/`, and `outcomes/` GCS objects.
It does not generate or impute missing answers.

Use investigator-authorized `gcloud auth login` credentials; GCS reads only.
The export requires no native LSM inference, LLM calls, or model replay.

## Reproduce the dataset

From the repository root:

```bash
git pull --ff-only origin experiment/prolific-human-study

python3 human_study/scripts/export_dtag_analysis_data.py \
  --audit-dir /tmp/dtag_full_audit \
  --key-file "$HOME/.config/dtag/private_analysis_hmac_key.bin" \
  --out "$HOME/private/dtag-analysis-2026-10-30" \
  --strict
```

**Keep the private key** securely backed up: it controls stable
`participant_uid` and `session_uid` across reruns. The script creates it
if absent, with mode 0600; future runs must reuse the same key. Both the
key and exported tables must live outside the Git repository.

Options:

- `--include-tests`: include discovered pilot, staging and GCP-test studies;
  by default exports **only the five known production studies**.
- `--include-text`: also include sensitive participant free-text answers
  and exact evidence snippets in private tables (off by default).
- `--strict`: require 15 approved PIDs in **each** of the two recent Prolific
  cohorts and a complete Q1–Q20 archived trajectory for each.

The script refuses to overwrite an existing output folder. To refresh,
choose a new dated directory.

## Tables and joins

Every analysis table uses deterministic, keyed `session_uid`, and uses
`participant_uid` for repeated-person awareness across different studies.
Do not treat one Firestore session as necessarily a distinct individual.

| File | Unit of observation | Main columns |
|---|---|---|
| `sessions.csv` | One observed DTAG session, including unfinished | `session_uid`, `participant_uid`, `dtag_study_id`, `prolific_campaign_id`, `recruitment_cohort`, `protocol`, `policy`, `approval_status`, archive completeness, baseline/final LSM index, config hash |
| `steps.csv` | One observed index point at baseline (t=0) or after answered adaptive question t=1…20 | `session_uid`, `step`, `index`, `delta_from_baseline`, `observed_step_delta`, `predicted_target_only_delta`, `accepted_assignment_count` |
| `questions.csv` | One answered question (baseline, intervention, outcome, attention) | `question_uid`, `session_uid`, `phase`, `adaptive_step`, `target_variable`, `question_text`, `mapping_status`, response time, attention pass, observed/predicted model indices, assignment/rejection counts |
| `assignments.csv` | One **accepted native survey-variable observation**, including multi-variable mappings | `question_uid`, `mapped_variable`, `native_value`, `confidence`, `revises_prior`, `assignment_type` |
| `flags.csv` | One validation issue, if any | `code`, `session_uid`, `detail` |
| `PRIVATE_id_crosswalk.csv` | One session with exact protected IDs | `session_uid`, `participant_uid`, DTAG local session ID, Prolific PID / STUDY_ID / SESSION_ID |
| `manifest.json` | Provenance and audit counts | Cohort and study counts, flags, HMAC-key fingerprint, GCS source, export settings |

Default `sessions.csv`, `steps.csv`, `questions.csv` and
`assignments.csv` exclude actual Prolific PIDs and DTAG session IDs.
They are **pseudonymized, not necessarily anonymous**, and remain private.
Provenance GCS object paths are HMAC-tokenized in these tables, so they do not
accidentally reveal the underlying local session ID.

For a participant-level panel, join `steps.csv` to `sessions.csv`
using `session_uid`. For each response's complete accepted survey evidence,
join `questions.csv` to `assignments.csv` on
`(session_uid, question_uid)`. A single response can contribute more
than one assignment; do not deduplicate to its target variable.

## Scientific and cohort distinctions

- **Democratic externally recruited / Right push**:
  `6ae37b8688d760488b8df1b0`.
- **Republican externally recruited / Right push**:
  `6ae3d74f4c7ff7370986b1e4`.
- Both have no six-question calibration baseline; the recorded t=0 index
  reflects the *unconditioned LSM state*, not participant-specific ideology.
- Older randomized four-arm, fixed-left, and fixed-right studies **have six
  baseline questions**; they are separate cohorts and should not be pooled
  with zero-calibration recruitment without careful stratification.
- `approval_status=approved_paid` is based on matching Prolific invoice PIDs
  to the exact study/campaign; `not_on_approved_invoice` does *not*
  necessarily mean a participant failed quality control.
- `predicted_target_only_delta` concerns the chosen question's predicted
  impact, while `observed_step_delta` conditions on **all newly accepted
  variables**. They are not identically scoped estimands.
- The index trajectory is **response-conditioned reconstruction of an LSM
  survey phenotype**, not independently demonstrated persuasion or human
  opinion change.

## Validation

The exporter verifies per-object SHA-256 archive integrity when present,
compares study/campaign/policy IDs with the audit, requires contiguous
Q1–Q20 points for `complete_20_archive=true`, and flags endpoint
inconsistencies. It retains **actual observed steps only** for incomplete
sessions and never carries forward a last observation to Q20.

For the October 30, 2026 aggregate audit the expected **reference counts**
are 120 production session records, 102 nominally 20-answer sessions, and
101 finalized 20-answer GCS archives. The export may differ from these
counts when subsequent data arrive or when a recorded archived answer lacks
an index point; inspect `manifest.json` and `flags.csv`. It must confirm
15 complete approved participants per recent recruitment campaign.

**Testing:** The exporter passed an offline fixture representing 30 approved,
fully archived participants (15 per campaign) with 600 question records and
630 longitudinal index points, plus a separate mixed partial-session fixture.
These fixtures are artificial and are **not** the actual DTAG participant data.
The live GCP export must be executed from an authorized workstation.
