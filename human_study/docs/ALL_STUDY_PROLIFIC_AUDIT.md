# DTAG / Prolific: all-study participant-linkage audit

**Prepared:** October 30, 2026. **Script:** [`human_study/scripts/audit_all_dtag_prolific.py`](../scripts/audit_all_dtag_prolific.py).

## What was directly verified from the uploaded PDFs

| Recruitment roster | Payment summary ID | Approved participant IDs | Total participant rewards | Prolific campaign `STUDY_ID` (investigator-declared) |
|---|---|---:|---:|---|
| `DTAG_right_DEM` | `RT6EDQ` | 15 distinct | $165.00 | `6ae37b8688d760488b8df1b0` |
| `DTAG_right_REP` | `J89GOE` | 15 distinct | $165.00 | `6ae3d74f4c7ff7370986b1e4` |

The two sets of 15 Prolific PIDs **do not overlap**. The PDF title identifies a right-push recruitment campaign but does **not** contain the machine-readable Prolific `STUDY_ID` in the document; those identifiers come from the campaign filenames and the versioned DTAG investigator mapping. The live audit requires exact PID equality, stored campaign `STUDY_ID`, correct DTAG study, and policy `right`.

An invoice lists **approved paid participants only**. It cannot establish the number who attempted, were returned, declined consent, failed attention checks, or never opened DTAG.

## Run

Run on a machine with permission to read project `pkcsaas-01`, Firestore database `dtag-human-pilot`, and GCS bucket `pkcsaas-01-dtag-study-data`.

```bash
python3 -m pip install PyMuPDF
gcloud auth login
python3 human_study/scripts/audit_all_dtag_prolific.py \
  --dem-pdf /private/DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf \
  --rep-pdf /private/REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf \
  --out /private/dtag_cohort_audit_2026-10-30 \
  --strict
```

`--out` must be a **new** directory. The script refuses to overwrite prior audits. All outputs are created in a private directory with filesystem mode `0700`, files `0600`. Do **not** run `git add` on the results folder. If access to the collection-group scan is unavailable, the script falls back to known and GCS-discovered study IDs, and explicitly reports that the Firestore enumeration may be incomplete.

For a fast diagnostic that **does not** verify GCS archives, add `--skip-gcs`; archive counts will be marked `NOT_CHECKED` in the paid-roster table.

## Outputs

- `all_studies.csv`: every discovered DTAG study, **all** sessions (including unfinished), unique consented Prolific PIDs, full 20-answer session count, GCS archive count, observed arms, and campaign IDs. The original four-arm study is **not** truncated to its previous manuscript's 24 completers.
- `all_cohorts_by_campaign_and_arm.csv`: stratifies every study by actual stored `prolific_study_id` and assigned policy rather than grouping all rightward arms together.
- `latest_pdf_roster_reconciliation.csv`: verified payment rosters versus exact Firestore study+campaign linkage, 20-answer progress, and GCS final archives.
- `PRIVATE_participant_crosswalk.csv`: all 30 approved Prolific IDs, their exact DTAG session IDs, observed policies, progress, and GCS completeness.
- `PRIVATE_all_sessions.csv`: participant-level records across every discoverable DTAG study, including unfinished sessions and archived-only sessions.
- `PRIVATE_issues.csv`: mismatches with identifiers to enable precise investigator remediation.
- `summary.json`: aggregated inventory and issue type counts without participant IDs.

## Assumptions and limitations

Five known production protocol IDs are pre-registered with their true baseline lengths and intended arms:

1. `prolific-v3-human-opinions-2026-10`: 6 baseline, 20 adaptive, randomized four-arm.
2. `prolific-v3-left-followup-2026-10`: 6 baseline, 20 adaptive, fixed left.
3. `prolific-v3-right-followup-2026-10`: 6 baseline, 20 adaptive, fixed right.
4. `dtag-v3-nocal-left-2026-10`: 0 baseline, 20 adaptive, fixed left.
5. `dtag-v3-nocal-right-2026-10`: 0 baseline, 20 adaptive, fixed right, the two new campaigns.

Additional test, staging, and short-pilot study IDs are discovered and counted, but their calibration length is labeled `UNKNOWN` until specifically registered. They are **not** falsely flagged as needing 20 answers. If the original production human study has 31 session records and only 24 completed, for example, the report displays both numbers separately.

The first three calibrated studies contributed **24 + 15 + 10 = 49** completed sessions in the October 28 manuscript snapshot. Those are *historical manuscript totals*, not current database totals and not Prolific approved-submission counts. The script does not rely on them; it queries all currently accessible sessions and GCS final archives.

The two uploaded PDFs do not allow external Prolific confirmation of older campaigns. The script discovers their stored `prolific_study_id` and participant counts, but independent validation of their prescreens and approved/returned status requires older Prolific study exports/invoices.

This audit tests data provenance, experiment grouping, and endpoint recording. It does not establish true change in political beliefs.

## Reproducibility

The script has been tested on both uploaded PDFs and against a synthetic offline Firestore/GCS fixture that included 31 original sessions of which 24 were complete. It has **not** been executed against live GCP resources in this ChatGPT environment, which does not have `gcloud` credentials.