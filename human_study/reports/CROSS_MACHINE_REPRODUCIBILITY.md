# DTAG human-study reproduction on a different machine

**State as of 2026-10-30.** The experiment and post-processing code, the
aggregate Q4 findings, and the reconstruction tools are tracked on the public
GitHub `experiment/prolific-human-study` branch. The original session
`final.json` objects reside in restricted GCS under
`gs://pkcsaas-01-dtag-study-data/studies/`; Firestore session and answered
question records reside in Google Cloud project `pkcsaas-01`, database
`dtag-human-pilot`. A previously missing original-study Left session was
restored to GCS from its checksum-valid Firestore outbox and verified byte for
byte (object generation `1793395715911815`).

**IMPORTANT: a portable private snapshot is not yet verified in GCS.**
Its creation requires running the backup script using the investigator's
cloud credentials. GitHub alone is insufficient to reconstruct the private
cohort and maintain the original HMAC pseudonyms.

## Required inventory

| Component | Where | Reproduction requirement |
| --- | --- | --- |
| Experiment, audit, export, score, and plotting code | Public GitHub DTAG `experiment/prolific-human-study` | Pin the exact git commit recorded in snapshot provenance |
| Original GCS `final.json` and per-question source objects | Private `gs://pkcsaas-01-dtag-study-data/studies/` | Original experimental evidence; use immutable archived indices |
| Session state and recovery outbox | Firestore `pkcsaas-01/dtag-human-pilot` | For fresh audits, missing-object verification |
| Prolific Democratic/Republican approved-payment PDFs | Private workstation now; MUST be included in cloud snapshot | Needed by `audit_all_dtag_prolific.py` to reconstruct exact paid-roster provenance |
| Persistent HMAC key | Current workstation `~/.config/dtag/private_analysis_hmac_key.bin`; MUST back up to Secret Manager | Essential for matching prior `session_uid`/`participant_uid` and crosswalks |
| Full private audit + derived analysis + 21-step trajectories + Q4 diagnostics | Workstation `~/private` (audit in `/tmp/dtag_full_audit`); MUST be copied to protected GCS | Frozen source snapshot and independent post-processing |
| Q4 aggregate table and scoring definition | GitHub `human_study/reports/q4_resistance_2026-10-30.*` | Public non-identifiable analysis results |

The public results snapshot comprises 102 expected production GCS 20/20
completions (71 six-question-calibrated and 31 zero-calibration Right).
The calibrated directional analysis comprises 21 Left and 38 Right
sessions. The Q4 extended score is 38/38; the resistance classifier within
the initially Left / Right-push subset is 27/29 accurate. These counts are
validated by the backup script against the private export, not inferred from
GitHub's aggregate report alone.

## 1. Prepare source files on the existing machine

The following directories must exist:

```text
/tmp/dtag_full_audit/
~/private/dtag-analysis-2026-10-30-restored/
~/private/dtag-trajectories-2026-10-30-restored/
~/private/dtag-q4-resistance-restored/
~/.config/dtag/private_analysis_hmac_key.bin
```

If the private trajectories directory was not generated yet, run:

```bash
python3 human_study/scripts/export_private_trajectories.py \
  --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
  --out "$HOME/private/dtag-trajectories-2026-10-30-restored" \
  --expect-complete 102
```

Locate the **two original paid-submissions PDFs** and set absolute paths:

```bash
export DTAG_DEM_PDF="/absolute/private/path/DEMOCRATIC_recruitment_right_push_prolific_summary_detailed_6ae37b8688d760488b8df1b0.pdf"
export DTAG_REP_PDF="/absolute/private/path/REPUBLICAN_RECRUIOT_right_push_prolific_summary_detailed_6ae3d74f4c7ff7370986b1e4.pdf"
```

If they are no longer available outside Git, recover them **privately** from
the older commit that still contained them **before any further Git history
rewrite**, and check their PDF contents. Do not recommit them to public Git.

Authenticate and ensure the account has permission to read/write the protected
GCS bucket and to create/access a Google Secret Manager secret in project
`pkcsaas-01`:

```bash
gcloud auth login
gcloud config set project pkcsaas-01
git fetch origin experiment/prolific-human-study
git restore --source=origin/experiment/prolific-human-study --worktree -- \
    human_study/scripts/portable_research_snapshot.sh
```

## 2. Back up once to the restricted cloud project

```bash
bash human_study/scripts/portable_research_snapshot.sh backup
```

The script validates that public-access prevention and uniform bucket-level
access are enabled on the research bucket, validates 102 completed production
sessions and the Q4 result denominators, and checks the HMAC key. It then:

1. Creates or verifies the key in **Secret Manager** as
   `projects/pkcsaas-01/secrets/dtag-private-analysis-hmac-2026`.
   It refuses a key mismatch.
2. Packages the original payment PDFs, full private audit, private analysis
   export, derived individual/group trajectories, and Q4 outputs.
3. Records exact Git branch commit, the source analysis metadata, and
   SHA-256 checksums.
4. Uploads create-only to
   `gs://pkcsaas-01-dtag-study-data/private-analysis/reproducibility/2026-10-30-restored-v1/snapshot/`.
   Existing objects cannot be overwritten.

**Never upload the raw HMAC key to GCS, GitHub, or the previously used
`git-zeroknowledgediscovery-dtag` artifact bucket.** After the Secret Manager
copy is independently verified, review/decommission the old raw-key object
at `gs://git-zeroknowledgediscovery-dtag/private_analysis_hmac_key.bin`.
The former public Git pointer to that key was removed from the current branch,
but older Git history and any copied objects require separate review.

## 3. Restore and verify from a clean machine

Install Git, Python 3, Google Cloud CLI, and any analysis dependencies.
Authenticate to the same GCP project, then:

```bash
git clone https://github.com/zeroknowledgediscovery/DTAG.git
cd DTAG
git fetch origin experiment/prolific-human-study
git checkout --detach origin/experiment/prolific-human-study

gcloud auth login
gcloud config set project pkcsaas-01
bash human_study/scripts/portable_research_snapshot.sh restore
```

The restore command refuses to overwrite the target local directory.
It downloads **every** bundled file from GCS, checks all SHA-256 hashes
against the snapshot manifest, and retrieves/verifies the original HMAC key
from Secret Manager with `--out-file` so its bytes are preserved exactly.

After restoration, use the `git_checkout_commit` in
`snapshot_provenance.json` to select the exact code revision, rather than
using whatever is currently at the tip of the branch.

A simple Q4 replay with the restored inputs is:

```bash
python3 human_study/scripts/score_q4_right_resistance.py \
  --analysis-dir "$HOME/private/dtag-portable-2026-10-30-restored-v1/snapshot/analysis" \
  --out "$HOME/private/dtag-q4-replay"
```

Expected calibrated Left and Right sample sizes are **21 and 38**,
Q4 resistance prediction 27/29 correct and extended Right success 38/38.
Compare the regenerated CSV/JSON with the saved `snapshot/q4/` files.

For independent *fresh* reconstruction from the cloud source archives,
the repository provides (in order):

1. `human_study/scripts/audit_all_dtag_prolific.py` using restored PDFs,
   Firestore and GCS, and a **new** private audit directory.
2. `human_study/scripts/export_dtag_analysis_data.py` using that audit,
   the GCS objects, and the recovered HMAC key.
3. `human_study/scripts/export_private_trajectories.py` using the private
   analysis export.
4. `human_study/scripts/score_q4_right_resistance.py` using its indexed
   trajectories.

New experimental enrollments after this freeze can change live audit totals;
the cloud snapshot contains the exact earlier cohort and its source identifiers.

## Scope and access

This checklist recreates the **stored experimental results and scientific
post-processing pipeline**. Re-deploying the interactive participant-facing
webapp or re-running the native LSM generation pipeline also requires its
configured native models, live services, source-code dependencies, service
identities, cloud deployment configuration, and third-party API credentials.
Those are distinct production-operational dependencies and are not certified
by this snapshot.

The snapshot contains sensitive participant-level research data, even though
some files use HMAC pseudonyms. Never publish the private snapshot, original
Prolific PDFs, or the HMAC key.
