#!/usr/bin/env bash
# Separate right-only DTAG service: does not redeploy the original four-arm app.
# Default is staging + dry-run; paid production requires NEW Prolific codes.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
export GCP_PROJECT="${GCP_PROJECT:-pkcsaas-01}"
export GCP_REGION="${GCP_REGION:-us-east1}"
export GCP_SERVICE=dtag-human-right
export GCP_SETTINGS_SERVICE=dtag-human-pilot
export DTAG_DEPLOY_ENV="${DTAG_DEPLOY_ENV:-staging}"

case "$DTAG_DEPLOY_ENV" in
  staging)
    export DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.right_followup.staging.yaml"
    export DTAG_MIN_INSTANCES="${DTAG_MIN_INSTANCES:-0}"
    ;;
  production)
    export DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.right_followup.yaml"
    export DTAG_MIN_INSTANCES="${DTAG_MIN_INSTANCES:-1}"
    ;;
  *)
    echo "DTAG_DEPLOY_ENV must be staging or production" >&2
    exit 1
    ;;
esac

# Google Cloud documents the deterministic service URL as service-projectNumber.region.run.app.
# A new service has no status.url until its first deployment, so discover projectNumber.
PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')"
[[ "$PROJECT_NUMBER" =~ ^[0-9]+$ ]] || { echo "Cannot determine GCP project number" >&2; exit 1; }
export DTAG_PUBLIC_ORIGIN="https://$GCP_SERVICE-$PROJECT_NUMBER.$GCP_REGION.run.app"

bash "$ROOT/human_study/deploy/deploy.sh" "$@"

if [[ "${1:-}" == --execute ]]; then
  ACTUAL_URL="$(gcloud run services describe "$GCP_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')"
  if [[ "$ACTUAL_URL" != "$DTAG_PUBLIC_ORIGIN" ]]; then
    echo "ERROR: deployed service URL $ACTUAL_URL differs from configured origin $DTAG_PUBLIC_ORIGIN" >&2
    echo "Resolve the origin mismatch before sending participants to this service." >&2
    exit 1
  fi
  printf 'Right-only DTAG URL: %s/study\n' "$ACTUAL_URL"
  if [[ "$DTAG_DEPLOY_ENV" == staging ]]; then
    echo "STAGING ONLY: no paid Prolific recruitment and no production completion codes."
  fi
else
  printf 'Planned right-only DTAG URL: %s/study\n' "$DTAG_PUBLIC_ORIGIN"
fi
