# DTAG human/Prolific cohort registry and reproduction

**Snapshot date:** 2026-10-30. The current versioned aggregate baseline is
[`reports/prolific_audit_2026-10-30.json`](../reports/prolific_audit_2026-10-30.json).
The current study-to-recruitment label mapping is
[`config/prolific_campaign_map.json`](../config/prolific_campaign_map.json).

## What is versioned, and what is private

This is a **public** GitHub repository. Do **not** commit payment invoices,
Prolific PIDs, SESSION_ID values, DTAG internal session IDs, participant prose,
`PRIVATE_*.csv`, or investigator archives containing personal data.

Versioned in Git:
- Investigator-declared **campaign ID → recruitment cohort → policy** mapping;
- Read-only audit implementation and an aggregate-only snapshot exporter;
- Dated, aggregate study counts, paid-roster match counts, outstanding issue
  types, source-PDF SHA-256 fingerprints, and GCP source namespaces.

Retained outside Git (restricted access, ideally durable encrypted investigator
storage): original Prolific payment PDFs/participant CSVs; exact PDF-to-Prolific
campaign association record; `PRIVATE_participant_crosswalk.csv`,
`PRIVATE_all_sessions.csv`, and `PRIVATE_issues.csv` from the audit;
the source `summary.json` (aggregate but keep alongside the other evidence).

The original participant-level linkages are also in the protected DTAG
Firestore/GCS records, including `prolific_pid`, `prolific_study_id`,
`prolific_session_id`, internal `session_id`, policy, and GCS final
archive. The saved PDFs provide the independent list of approved paid PIDs.
The roster crosswalk **cannot be independently reproduced from the public
aggregate JSON alone**. Retain the PDFs privately.

## Confirmed latest right-push cohorts

| Prolific title | Declared Prolific campaign ID | External recruitment | Paid approved | Exact stored study+campaign matches | 20-answer GCS finals |
|---|---|---|---:|---:|---:|
| `DTAG_right_DEM` | `6ae37b8688d760488b8df1b0` | Democrat | 15 | 15 | 15 |
| `DTAG_right_REP` | `6ae3d74f4c7ff7370986b1e4` | Republican | 15 | 15 | 15 |

Both campaigns use `dtag-v3-nocal-right-2026-10`, `fixed_arm: right`,
zero preliminary baseline questions, and 20 adaptive questions. The PDFs
list approved payments; they do not independently print Prolific STUDY_ID.
The exact PID matches in Firestore support the investigator-declared campaign
association. Treat campaign **recruitment** as distinct from LSM-inferred ideology.

The larger DTAG study contained 36 session records, 36 stored Prolific IDs,
31 20-answer sessions and 31 GCS 20-answer finals at the snapshot. **Only
30 of those are matched to the two approved-payment rosters.** The extra
completed archive and the six non-approved-in-invoice session records should
not be silently assigned to either paid cohort.

## Original and previous production studies

As of the 2026-10-30 audit output:

| Study | Session records | Unique consented Prolific PIDs | 20-answer sessions | Final 20-answer GCS archives |
|---|---:|---:|---:|---:|
| `prolific-v3-human-opinions-2026-10` | 30 | 30 | 25 | 24 |
| `prolific-v3-left-followup-2026-10` | 18 | 17 | 15 | 15 |
| `prolific-v3-right-followup-2026-10` | 36 | 35 | 31 | 31 |
| `dtag-v3-nocal-left-2026-10` | 0 | 0 | 0 | 0 |
| `dtag-v3-nocal-right-2026-10` | 36 | 36 | 31 | 31 |

The snapshot JSON additionally preserves pilot, staging, and GCP-test
studies; they must not be pooled into the production human analysis without
explicit inclusion decisions. Manuscript results reporting 24 original
completers or 49 historically pooled completers are **not** total recruitment
figures and are not current counts.

## Reproduce the complete audit with private source PDFs

From the repository root on an investigator-authorized GCP workstation:

```bash
python3 -m pip install PyMuPDF
gcloud auth login

python3 human_study/scripts/audit_all_dtag_prolific.py \
  --dem-pdf /private/DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf \
  --rep-pdf /private/REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf \
  --out /private/dtag_full_audit_YYYY_MM_DD \
  --strict
```

The audit scans Firestore collection-group `sessions`, discovers GCS final
archives, reconciles paid Prolific PIDs to stored study/campaign IDs and
policy, and outputs `summary.json`, aggregate CSVs and private per-person
crosswalk/issue tables. Confirm `Firestore scan: FULL_COLLECTION_GROUP`.
The `--strict` flag addresses critical paid-participant linkage/policy
failures; **a zero exit status does not mean all other issue types are gone**.

## Publish a new sanitized aggregate snapshot

After auditing the private `PRIVATE_issues.csv` and before committing,
run the aggregate-only publisher:

```bash
python3 human_study/scripts/publish_prolific_audit_snapshot.py \
  --summary /private/dtag_full_audit_YYYY_MM_DD/summary.json \
  --dem-pdf /private/DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf \
  --rep-pdf /private/REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf \
  --out human_study/reports/prolific_audit_YYYY-MM-DD.json
```

Replace YYYY-MM-DD with the actual audit date, and choose a new filename
rather than overwriting the historical snapshot. Inspect the JSON before
committing; never `git add` the private audit output directory.

For long-term participant-level reproducibility, retain the **original**
Prolific source PDFs and restricted `PRIVATE_*.csv` files in a
permission-controlled private investigator archive. An optional location is
the existing private DTAG GCS bucket under a dedicated restricted investigator
prefix (subject to a storage/access policy review). Store the invoice
SHA-256 values alongside that archive. **Do not rely on temporary `/tmp`
storage** for the only copy of these records.

## Known unresolved audit flags (not assumed to concern the 30 paid cohort)

The 2026-10-30 scan reported:
- 12 `COMPLETE_NO_GCS_FINAL`
- 16 `CONSENTED_CAMPAIGN_MISSING`
- 16 `CONSENTED_PID_MISSING`
- 6 `DTAG_PID_NOT_APPROVED_IN_PDF`
- 5 `INVALID_PROGRESS`
- 4 `MULTIPLE_CONSENTED_SESSIONS_SAME_PID`
- 2 `PID_IN_MULTIPLE_STORED_CAMPAIGNS`

These are **global issue counts across discovered production, pilot and
test studies**. Investigate using the protected `PRIVATE_issues.csv`
before attributing them to a particular participant or study. Do not
alter archived observations merely to force counts to match.

The observed changes in the LSM ideological index measure
**response-conditioned phenotype refinement**, not demonstrated changes
in participants' political beliefs.
