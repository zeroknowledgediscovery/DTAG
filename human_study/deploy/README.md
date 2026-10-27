# DTAG participant apps: URLs and deployment

This runbook covers the two DTAG human-study Cloud Run services on
**GCP project `pkcsaas-01`, region `us-east1`**. Execute commands from the
root of the DTAG checkout on `lightsabr`, on branch
`experiment/prolific-human-study`.

## Application URLs and study isolation

| App | Cloud Run service | Participant URL | Current intended mode |
| --- | --- | --- | --- |
| Original, four-arm study | `dtag-human-pilot` | https://dtag-human-pilot-gp7m2nymma-ue.a.run.app/study | Paid Prolific production; `right/left/neutral/random` |
| Right-arm-only follow-up | `dtag-human-right` | https://dtag-human-right-gp7m2nymma-ue.a.run.app/study | Internal staging/test only, until new Prolific study is configured |

These are the **canonical URLs returned by Cloud Run's `status.url`** during
the October 2026 deployments. Do not assume that the alternate
`...-75214764470.us-east1.run.app` hostname is interchangeable for browser
requests: the backend enforces **exact** `DTAG_PUBLIC_ORIGIN` on API POST
requests to prevent cross-origin submissions.

Both services reuse the existing private GCS bucket
`gs://pkcsaas-01-dtag-study-data`, Firestore database from the original
service, runtime identity, and Secret Manager secrets. **Do not provision a new
bucket or database.** Scientific and participant data are isolated by the
distinct `study_id` values:

| Instrument | Study ID | Config file |
| --- | --- | --- |
| Existing four-arm paid study | `prolific-v3-human-opinions-2026-10` | `human_study/config/study.prolific.production.yaml` |
| New right-only test | `prolific-v3-right-followup-staging-2026-10` | `human_study/config/study.prolific.right_followup.staging.yaml` |
| New right-only paid follow-up **(draft; NOT yet approved)** | `prolific-v3-right-followup-2026-10` | `human_study/config/study.prolific.right_followup.yaml` |

The question schedule remains 6 baseline + 20 native-adaptive + 5 interleaved
attention checks, 31 total. The original study randomizes among four arms. The
right-only study sets `fixed_arm: right` after the baseline and archives the
assignment as `fixed-single-arm-right-v1`. No participant already active on
the original service should be moved to the new one.

## Refresh checkout and run the checks

```bash
git switch experiment/prolific-human-study
git pull --ff-only origin experiment/prolific-human-study
bash human_study/scripts/check_v3.sh
```

These tests are local/automated checks, not proof of a successful live
participant journey.

## Deploy or redeploy the *right-only staging* app

Explicitly set `DTAG_DEPLOY_ENV=staging`: your shell might still export
`production` from an earlier paid-study deployment.

```bash
# See what would be deployed (dry run; no Cloud Run changes).
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_right_followup.sh

# Build and deploy the new/separate dtag-human-right service.
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_right_followup.sh --execute
```

The wrapper (`deploy_right_followup.sh`) selects `dtag-human-right` while
`deploy.sh` otherwise defaults to `dtag-human-pilot`. It reuses the pilot's
GCS and Firestore settings, computes the new service's exact origin using
Cloud Run's reported URL, and sets **0 minimum instances for staging**. The
first deployment created the service; later invocations redeploy it.
The original four-arm service is **not** redeployed.

Staging uses `required: false` for Prolific IDs and **test-only completion
codes**, and is **not** suitable for paid Prolific participants. A participant
can open its `/study` URL directly without Prolific URL parameters.

## Check the new service URL, status and origin

```bash
URL=$(gcloud run services describe dtag-human-right \
  --project pkcsaas-01 --region us-east1 \
  --format='value(status.url)')
echo "Right-only study: $URL/study"

STUDY_URL="$URL" bash human_study/deploy/smoke.sh

# Inspect the actual browser origin in the live Cloud Run environment.
gcloud run services describe dtag-human-right \
  --project pkcsaas-01 --region us-east1 --format=json \
  | python3 -c '
import json, sys
s = json.load(sys.stdin)
env = s["spec"]["template"]["spec"]["containers"][0]["env"]
for k in ("DTAG_ENV", "DTAG_PUBLIC_ORIGIN", "DTAG_GCS_BUCKET",
          "DTAG_FIRESTORE_DATABASE"):
    print(k, "=", next((x.get("value") for x in env
                        if x.get("name") == k), "(missing)"))
'
```

The smoke probe checks `/api/human/health`,
`/api/human/readiness`, and `/study`. These probes **do not test the POST
submission flow**. To verify that as well, open `$URL/study`, accept the
test-study consent, answer initial questions, and confirm that answers advance
without HTTP 403; the baseline must result in the **right** policy assignment
after six substantive responses. Refresh/resume to check session persistence.

### Fix the initial Cloud Run URL mismatch *without rebuilding*

The very first `dtag-human-right` deployment succeeded, but the older wrapper
mistakenly assumed the alternate project-number URL would equal Cloud Run's
reported `status.url`. The result was an incorrect
`DTAG_PUBLIC_ORIGIN`, which can cause browser POST requests to fail with
HTTP 403. The wrapper has since been corrected in the repository.

For an **already deployed** app, apply this one-time configuration-only fix:

```bash
URL=$(gcloud run services describe dtag-human-right \
  --project pkcsaas-01 --region us-east1 \
  --format='value(status.url)')

gcloud run services update dtag-human-right \
  --project pkcsaas-01 --region us-east1 \
  --update-env-vars "DTAG_PUBLIC_ORIGIN=$URL"

STUDY_URL="$URL" bash human_study/deploy/smoke.sh
```

The command creates a Cloud Run configuration revision but does **not**
rebuild the container or modify the original app.

## Deploy the original four-arm app (only when safe to update)

**Do not redeploy `dtag-human-pilot` while participants are in progress.**
Use its existing frozen instrument and deployment path.

```bash
# Dry-run
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy.sh

# Deploy ONLY when participant sessions can safely transition
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy.sh --execute
```

The original service reads the production-reviewed config from
`human_study/config/study.prolific.production.yaml`, which includes the original
Prolific completion codes. Deploying without `DTAG_DEPLOY_ENV=production`
defaults to staging and can substitute the test instrument.

## Activate *paid Prolific* mode for the right-only follow-up

**Not ready yet.** The paid right-only config currently has
`reviewed: false`, `prolific.required: true`, and
`CHANGEME01/02/03` placeholders. The deployment script intentionally refuses
that config.

1. Create a **new Prolific study** for the right-only follow-up, with its own
   default-completion, failed-attention-check (manual review), and no-consent
   (request return) completion codes. Do **not** reuse codes from the original
   paid study.
2. On the Prolific participant-eligibility screen, **exclude participants in
   the previous DTAG study**, including those with pending/incomplete
   submissions as supported by the Prolific filter. The production right-only
   backend additionally checks prior consenting Prolific IDs in the original
   Firestore study namespace. Keep those old Firestore enrollment records.
3. Enter the three *new* codes in
   `human_study/config/study.prolific.right_followup.yaml`, verify the consent,
   estimated 20-minute duration, reward and scientific protocol, then set
   `reviewed: true`. Commit the reviewed YAML before deploying.
4. Run regression tests and a dry run. When reviewed, deploy the paid config
   **to the separate right-only service**:

```bash
bash human_study/scripts/check_v3.sh

DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_right_followup.sh

DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_right_followup.sh --execute
```

For the *new* Prolific study's external URL, configure URL parameters to
pass actual participant/study/submission identifiers:

```text
https://dtag-human-right-gp7m2nymma-ue.a.run.app/study?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Verify that a Prolific participant preview substitutes all three placeholders
with real values and that the new app stores them correctly. Test the normal,
review and no-consent completion paths *before* public recruitment. The backend
does not independently authenticate a Prolific PID against Prolific: the
Prolific eligibility filter is the primary exclusion control, and the
server-side Firestore check is additional protection for prior **consented**
participants.

## Read archived sessions (do not delete study data)

```bash
gcloud storage ls \
  'gs://pkcsaas-01-dtag-study-data/studies/'
```

Use the separate `study_id` prefixes above to distinguish the historical
four-arm, right-only staging, and future paid right-only data. Never delete
the original-study Firestore enrollments to "reset" the new study, since the
paid follow-up consults them to exclude prior consenting participants.

## Deployment files

- `human_study/deploy/deploy.sh`: common Cloud Build + Cloud Run deployer;
  supports dry-run vs `--execute` and selects staging/production.
- `human_study/deploy/deploy_right_followup.sh`: right-only service wrapper,
  study config selector and canonical-origin reconciliation.
- `human_study/deploy/smoke.sh`: read-only health/readiness/landing-page checks.
- `human_study/config/study.prolific.production.yaml`: frozen four-arm paid config.
- `human_study/config/study.prolific.right_followup.staging.yaml`: right-only internal test.
- `human_study/config/study.prolific.right_followup.yaml`: right-only paid draft.
