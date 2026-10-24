#!/usr/bin/env bash
# Run from the DTAG checkout. Default is a reviewable dry run.
set -euo pipefail
EXECUTE=0
[[ "${1:-}" != --execute ]] || EXECUTE=1
: "${GCP_PROJECT:?Set an isolated project ID}"
: "${DTAG_GCS_BUCKET:?Set private bucket name}"
: "${DTAG_REVIEWED_CONFIG:?Set a path to the reviewed, native-validated YAML instrument}"
REGION="${GCP_REGION:-us-east1}"
SERVICE="${GCP_SERVICE:-dtag-human-pilot}"
ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git rev-parse HEAD)"
IMAGE="$REGION-docker.pkg.dev/$GCP_PROJECT/dtag-study/pilot:$COMMIT"
[[ -z "$(git status --porcelain)" ]] || { printf '%s\n' 'Commit/review source changes before building.' >&2; exit 1; }
test -f "$DTAG_REVIEWED_CONFIG"
PYTHONPATH="$ROOT/human_study/backend:$ROOT/scripts:$ROOT" python - "$DTAG_REVIEWED_CONFIG" <<'PY'
import sys
from human_study.study_config import StudyConfig
c = StudyConfig.load(sys.argv[1])
if not c.reviewed or not 12 <= len(c.bank('baseline')) <= 15:
    raise SystemExit('Deployment requires an explicitly reviewed 12–15-item baseline instrument')
PY
run() { if [[ "$EXECUTE" == 1 ]]; then "$@"; else printf '%q ' "$@"; printf '\n'; fi; }
# Archive only tracked source: no local responses, caches, .env files or Git credentials.
CONTEXT="$(mktemp -d)"
trap 'rm -rf "$CONTEXT"' EXIT
git archive HEAD | tar -x -C "$CONTEXT"
# This explicit file contains reviewed instrument text/options only, never participant data or secrets.
cp "$DTAG_REVIEWED_CONFIG" "$CONTEXT/human_study/config/reviewed.yaml"
run gcloud builds submit "$CONTEXT" --config "$ROOT/human_study/deploy/cloudbuild.yaml" --project "$GCP_PROJECT" --region "$REGION" --service-account "projects/$GCP_PROJECT/serviceAccounts/dtag-build@$GCP_PROJECT.iam.gserviceaccount.com" --substitutions "_IMAGE=$IMAGE,_COMMIT=$COMMIT"
run gcloud run deploy "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --image "$IMAGE" \
 --service-account "dtag-study@$GCP_PROJECT.iam.gserviceaccount.com" --allow-unauthenticated \
 --cpu 2 --memory 4Gi --concurrency 2 --max-instances 2 --min-instances 0 --timeout 300 \
 --set-env-vars "DTAG_ENV=staging,DTAG_STUDY_CONFIG=/src/human_study/config/reviewed.yaml,DTAG_GCS_BUCKET=$DTAG_GCS_BUCKET,DTAG_LLM_BACKEND=openai,DTAG_FIRESTORE_DATABASE=${DTAG_FIRESTORE_DATABASE:-(default)}" \
 --set-secrets 'DTAG_COOKIE_SECRET=dtag-cookie-secret:latest,OPENAI_API_KEY=dtag-openai-api-key:latest'
run gcloud run services describe "$SERVICE" --project "$GCP_PROJECT" --region "$REGION" --format 'value(status.url)'
