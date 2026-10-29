# DTAG participant apps: URLs and deployment

This runbook covers the DTAG human-study Cloud Run services on
**GCP project `pkcsaas-01`, region `us-east1`**. Execute commands from the
root of the DTAG checkout on `lightsabr`, on branch
`experiment/prolific-human-study`.

## Application URLs and study isolation

| App | Cloud Run service | Participant URL | Current intended mode |
| --- | --- | --- | --- |
| Original, four-arm study | `dtag-human-pilot` | https://dtag-human-pilot-gp7m2nymma-ue.a.run.app/study | Paid Prolific production; `right/left/neutral/random` |
| Right-arm-only follow-up | `dtag-human-right` | https://dtag-human-right-gp7m2nymma-ue.a.run.app/study | Existing right-only service |
| Left-arm-only follow-up | `dtag-human-left` | Cloud Run `status.url` after deployment | New staging service; paid study requires Prolific codes |

The two existing URLs are **canonical URLs returned by Cloud Run's `status.url`**
during the October 2026 deployments. The left-only URL is not active
until that service is deployed. Do not assume that the alternate
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
| New left-only internal test | `prolific-v3-left-followup-staging-2026-10` | `human_study/config/study.prolific.left_followup.staging.yaml` |
| New left-only paid follow-up **(configured)** | `prolific-v3-left-followup-2026-10` | `human_study/config/study.prolific.left_followup.yaml` |

The question schedule remains 6 baseline + 20 native-adaptive + 5 interleaved
attention checks, 31 total. The original study randomizes among four arms. The
right-only study sets `fixed_arm: right` after the baseline and archives the
assignment as `fixed-single-arm-right-v1`. No participant already active on
the original service should be moved to the new one.

## Deploy the left-only app (new, separate service)

The left-only counterpart uses **`dtag-human-left`** in `pkcsaas-01/us-east1`.
It retains the six baseline questions, 20 adaptive steps, five interleaved
attention checks, native LSM model and storage infrastructure. After baseline,
`fixed_arm: left` deterministically archives `fixed-single-arm-left-v1`.
Neither the original four-arm service nor the right-only service is modified.

From the repository root, deploy **staging** for testing:

```bash
git switch experiment/prolific-human-study
git pull --ff-only origin experiment/prolific-human-study
bash human_study/scripts/check_v3.sh
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_left_followup.sh
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_left_followup.sh --execute
```

The wrapper reads Cloud Run's canonical URL and prints the new participant link.
You can retrieve and smoke-test that URL at any time:

```bash
URL="$(gcloud run services describe dtag-human-left --project pkcsaas-01 \
  --region us-east1 --format='value(status.url)')"
echo "$URL/study"
STUDY_URL="$URL" bash human_study/deploy/smoke.sh
```

**Do not use staging for paid recruitment.** The left-only production YAML is
reviewed and configured with the three confirmed Prolific completion codes
from the existing study. It requires Prolific participant IDs and excludes
prior DTAG participants. Deploy paid production using:

```bash
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_left_followup.sh
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_left_followup.sh --execute
```

Use the real left-only origin in Prolific's external-study URL:

```text
https://<actual-left-cloud-run-host>/study?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

Verify actual participant links, normal/review/no-consent completion routes,
and full-session assignment. The paid left-only backend additionally
excludes consenting participants from existing four-arm and right-only
production study namespaces.

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


## No-calibration Left/Right studies (independent pilot)

These are NEW services. They do not modify `dtag-human-left`,
`dtag-human-right`, or `dtag-human-pilot`.

| Condition | Service | Staging namespace |
| --- | --- | --- |
| No-calibration Left | `dtag-human-nocal-left` | `dtag-v3-nocal-left-staging-2026-10` |
| No-calibration Right | `dtag-human-nocal-right` | `dtag-v3-nocal-right-staging-2026-10` |

The new service starts after consent directly with question 1 of 20
adaptive questions (plus five interleaved attention checks). There are
**no preliminary calibration questions**, and the six previously used
pole calibration variables are excluded from both the native question
selection and multi-variable answer mapping. The baseline index is
`adapter.index({})`: the same unconditioned LSM reference for every
participant, **not** the participant's externally measured ideology.
The Prolific party-affiliation prescreener belongs to recruitment
metadata; it is not used to seed the LSM in this design. Compare
Left versus Right conditional displacements using the new baseline;
do not mix these raw endpoint shifts with the original six-item-baseline
human cohorts without explicitly modeling the different initialization.

Staging is an internal research test with fabricated completion codes,
zero paid recruitment, and no Prolific ID requirement. Each new service
uses a distinct Firestore study collection and GCS study prefix.
No existing production service is redeployed. The staging instrument
has five checks after adaptive answers 3, 7, 11, 15, and 19.

From the repository root:

```bash
git switch experiment/prolific-human-study
git pull --ff-only origin experiment/prolific-human-study
PYTHONPATH=human_study/backend:scripts:. python3 -m pytest -q human_study/tests/test_v3_zero_baseline.py
# Dry runs; default env is staging:
bash human_study/deploy/deploy_nocal_left.sh
bash human_study/deploy/deploy_nocal_right.sh
# Deploy both NEW staging services:
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_nocal_left.sh --execute
DTAG_DEPLOY_ENV=staging bash human_study/deploy/deploy_nocal_right.sh --execute
```

Read the actual HTTPS service URLs from Cloud Run; do **not** infer
hostnames or publish unverified proposed addresses:

```bash
for service in dtag-human-nocal-left dtag-human-nocal-right; do
  url="$(gcloud run services describe "$service" --project pkcsaas-01 --region us-east1 --format='value(status.url)')"
  echo "$service: $url/study"
  STUDY_URL="$url" bash human_study/deploy/smoke.sh
done
```

Live workflow testing must cover consent -> first adaptive question with
`phase=intervention` (no baseline), 20 answered native adaptive steps,
five attention checks, stable policy, a complete archival final.json,
and an independently verified baseline index `I({})`.
A smoke probe alone does not test answer submission.

For **paid** Prolific recruitment, complete and investigator-review
`study.prolific.nocal.left.yaml` and
`study.prolific.nocal.right.yaml`, including distinct newly issued
Prolific completion/review/no-consent codes. Production configs are
deliberately `reviewed: false` with `CHANGEME` placeholders,
so they fail closed until explicitly approved. Exclude prior paid DTAG
participants and the other new study's paid participants. Do not
reuse staging URLs or test codes in Prolific. Obtain required ethics
approval for changes in protocol and consent.

When approved, deploy each independently:

```bash
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_nocal_left.sh --execute
DTAG_DEPLOY_ENV=production bash human_study/deploy/deploy_nocal_right.sh --execute
```

The same two links can serve four Prolific recruitment campaigns,
stratifying Democrats and Republicans externally within each policy.
Use the standard Prolific external-study link form with its standard
`PROLIFIC_PID`, `STUDY_ID`, and `SESSION_ID` URL placeholders.
Separate Prolific campaign IDs and prescreen metadata should be retained
for analysis; no party label is inferred from the participant's responses.
