#!/usr/bin/env bash
# Run from the DTAG checkout. Default is a reviewable dry run.
set -euo pipefail
EXECUTE=0
[[ "${1:-}" != --execute ]] || EXECUTE=1
# Reuse the already provisioned pilot project's Cloud Run configuration.
GCP_PROJECT="${GCP_PROJECT:-pkcsaas-01}"
REGION="${GCP_REGION:-us-east1}"
SERVICE="${GCP_SERVICE:-dtag-human-pilot}"
# Separate-service deployment can reuse the storage config of an existing app.
SETTINGS_SERVICE="${GCP_SETTINGS_SERVICE:-$SERVICE}"
# The active Cloud Run service is the source of truth for the existing archive bucket.
# No new bucket is created; an explicit DTAG_GCS_BUCKET still overrides discovery.
if [[ -z "${DTAG_GCS_BUCKET:-}" ]]; then
  DTAG_GCS_BUCKET="$(gcloud run services describe "$SETTINGS_SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format=json | python3 -c '
import json, sys
service = json.load(sys.stdin)
template = service.get("spec", {}).get("template", {})
containers = template.get("spec", {}).get("containers", []) or template.get("containers", [])
if not containers:
    containers = service.get("template", {}).get("containers", [])
for container in containers:
    for env in container.get("env", []):
        if env.get("name") == "DTAG_GCS_BUCKET" and env.get("value"):
            print(env["value"])
            sys.exit(0)
raise SystemExit("Existing Cloud Run service has no DTAG_GCS_BUCKET setting")
')"
fi
: "${DTAG_GCS_BUCKET:?Could not reuse existing Cloud Run archive bucket}"
# Reuse existing service's Firestore database if no override was supplied.
if [[ -z "${DTAG_FIRESTORE_DATABASE:-}" ]]; then
  DTAG_FIRESTORE_DATABASE="$(gcloud run services describe "$SETTINGS_SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format=json | python3 -c '
import json, sys
service = json.load(sys.stdin)
template = service.get("spec", {}).get("template", {})
containers = template.get("spec", {}).get("containers", []) or template.get("containers", [])
if not containers:
    containers = service.get("template", {}).get("containers", [])
for container in containers:
    for env in container.get("env", []):
        if env.get("name") == "DTAG_FIRESTORE_DATABASE" and env.get("value"):
            print(env["value"])
            sys.exit(0)
raise SystemExit("Existing Cloud Run service has no DTAG_FIRESTORE_DATABASE setting")
')"
fi
# Default to staging to avoid accidentally recruiting against a test deployment.
# Explicitly pass DTAG_DEPLOY_ENV=production for the paid Prolific instrument.
DEPLOY_ENV="${DTAG_DEPLOY_ENV:-staging}"
case "$DEPLOY_ENV" in staging|production) ;; *) echo "DTAG_DEPLOY_ENV must be staging or production" >&2; exit 1 ;; esac
ROOT="$(git rev-parse --show-toplevel)"
# Use the frozen committed instrument for the selected deployment environment.
if [[ -z "${DTAG_REVIEWED_CONFIG:-}" ]]; then
  if [[ "$DEPLOY_ENV" == production ]]; then
    DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.production.yaml"
  else
    DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.gcptest.yaml"
  fi
fi
DTAG_PUBLIC_ORIGIN="${DTAG_PUBLIC_ORIGIN:-$(gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format='value(status.url)')}"
: "${DTAG_PUBLIC_ORIGIN:?Could not read public HTTPS service URL}"
COMMIT="$(git rev-parse HEAD)"
IMAGE="$REGION-docker.pkg.dev/$GCP_PROJECT/dtag-study/pilot:$COMMIT"
[[ -z "$(git status --porcelain)" ]] || { printf '%s\n' 'Commit/review source changes before building.' >&2; exit 1; }
test -f "$DTAG_REVIEWED_CONFIG"
DTAG_DEPLOY_ENV="$DEPLOY_ENV" PYTHONPATH="$ROOT/human_study/backend:$ROOT/scripts:$ROOT" python - "$DTAG_REVIEWED_CONFIG" <<'PY'
import os
import sys
from human_study.study_config import StudyConfig
c = StudyConfig.load(sys.argv[1])
if not c.reviewed:
    raise SystemExit('Deployment requires an explicitly reviewed instrument')
if c.response_mode == 'click' and not 12 <= len(c.bank('baseline')) <= 15:
    raise SystemExit('Legacy study requires a 12–15-item baseline')
if c.response_mode in ('free_text_llm', 'free_text_multi') and not 0 <= len(c.bank('baseline')) <= 40:
    raise SystemExit('V3 needs 0–40 initial questions')
if c.prolific and any((x or '').upper().startswith('CHANGEME')
                      for x in (c.prolific.completion_code, c.prolific.review_code, c.prolific.no_consent_code)):
    raise SystemExit('Replace the placeholder Prolific completion codes')
if os.environ['DTAG_DEPLOY_ENV'] == 'production':
    if not c.prolific or not c.prolific.required:
        raise SystemExit('Production Prolific deployment requires PROLIFIC_PID linkage')
PY
run() { if [[ "$EXECUTE" == 1 ]]; then "$@"; else printf '%q ' "$@"; printf '\n'; fi; }
# Archive only tracked source: no local responses, caches, .env files or Git credentials.
CONTEXT="$(mktemp -d)"
trap 'rm -rf "$CONTEXT"' EXIT
git archive HEAD | tar -x -C "$CONTEXT"
# This explicit file contains reviewed instrument text/options only, never participant data or secrets.
cp "$DTAG_REVIEWED_CONFIG" "$CONTEXT/human_study/config/reviewed.yaml"
run gcloud builds submit "$CONTEXT" --config "$ROOT/human_study/deploy/cloudbuild.yaml" --project "$GCP_PROJECT" --region "$REGION" --service-account "projects/$GCP_PROJECT/serviceAccounts/dtag-build@$GCP_PROJECT.iam.gserviceaccount.com" --substitutions "_IMAGE=$IMAGE,_COMMIT=$COMMIT"
# Provision for ~10 simultaneous Prolific participants: up to 12 in-flight HTTP requests
# across 6 instances, with 3 warm instances to reduce native-model cold starts.
run gcloud run deploy "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --image "$IMAGE" \
 --service-account "dtag-study@$GCP_PROJECT.iam.gserviceaccount.com" --allow-unauthenticated \
 --cpu 2 --memory 4Gi --concurrency 2 --max-instances 6 --min-instances "${DTAG_MIN_INSTANCES:-3}" --timeout 300 \
 --set-env-vars "DTAG_ENV=$DEPLOY_ENV,DTAG_STUDY_CONFIG=/src/human_study/config/reviewed.yaml,DTAG_GCS_BUCKET=$DTAG_GCS_BUCKET,DTAG_LLM_BACKEND=openai,DTAG_FIRESTORE_DATABASE=${DTAG_FIRESTORE_DATABASE:-(default)},DTAG_PUBLIC_ORIGIN=$DTAG_PUBLIC_ORIGIN" \
 --set-secrets 'DTAG_COOKIE_SECRET=dtag-cookie-secret:latest,OPENAI_API_KEY=dtag-openai-api-key:latest'
run gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format 'value(status.url)'
