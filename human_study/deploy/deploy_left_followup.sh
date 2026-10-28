#!/usr/bin/env bash
# Separate left-only DTAG service: never redeploys the existing four-arm or right-only apps.
# Default is staging + dry-run; paid production requires NEW Prolific codes.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
export GCP_PROJECT="${GCP_PROJECT:-pkcsaas-01}"
export GCP_REGION="${GCP_REGION:-us-east1}"
export GCP_SERVICE=dtag-human-left
export GCP_SETTINGS_SERVICE=dtag-human-pilot
export DTAG_DEPLOY_ENV="${DTAG_DEPLOY_ENV:-staging}"

case "$DTAG_DEPLOY_ENV" in
  staging)
    export DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.left_followup.staging.yaml"
    export DTAG_MIN_INSTANCES="${DTAG_MIN_INSTANCES:-0}"
    ;;
  production)
    export DTAG_REVIEWED_CONFIG="$ROOT/human_study/config/study.prolific.left_followup.yaml"
    export DTAG_MIN_INSTANCES="${DTAG_MIN_INSTANCES:-1}"
    ;;
  *)
    echo "DTAG_DEPLOY_ENV must be staging or production" >&2
    exit 1
    ;;
esac

# The application's POST CSRF checks require the exact browser-visible origin.
# Cloud Run exposes multiple valid URL formats, and status.url can use the
# project-specific hash rather than the project-number hostname.
# Reuse this service's actual URL when already deployed.
CURRENT_URL="$(gcloud run services describe "$GCP_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)' 2>/dev/null || true)"
if [[ -n "$CURRENT_URL" ]]; then
  export DTAG_PUBLIC_ORIGIN="$CURRENT_URL"
else
  # On first creation use the existing pilot's canonical status.url hostname.
  # Both Cloud Run services are in the same GCP project and region.
  PILOT_URL="$(gcloud run services describe "$GCP_SETTINGS_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')"
  case "$PILOT_URL" in
    "https://$GCP_SETTINGS_SERVICE-"*)
      export DTAG_PUBLIC_ORIGIN="https://$GCP_SERVICE-${PILOT_URL#https://$GCP_SETTINGS_SERVICE-}"
      ;;
    *)
      echo "Cannot derive a first-deployment origin from existing pilot URL: $PILOT_URL" >&2
      exit 1
      ;;
  esac
fi

bash "$ROOT/human_study/deploy/deploy.sh" "$@"

if [[ "${1:-}" == --execute ]]; then
  ACTUAL_URL="$(gcloud run services describe "$GCP_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')"
  [[ "$ACTUAL_URL" == https://* ]] || { echo "Cloud Run returned no HTTPS service URL" >&2; exit 1; }
  if [[ "$ACTUAL_URL" != "$DTAG_PUBLIC_ORIGIN" ]]; then
    # Unexpected hostname divergence: fix the live origin without rebuilding.
    # Cloud Run creates one small configuration revision to correct CSRF checks.
    echo "Cloud Run selected $ACTUAL_URL; correcting DTAG_PUBLIC_ORIGIN on the deployed service."
    gcloud run services update "$GCP_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" \
      --update-env-vars "DTAG_PUBLIC_ORIGIN=$ACTUAL_URL"
  fi
  printf 'Left-only DTAG URL: %s/study\n' "$ACTUAL_URL"
  if [[ "$DTAG_DEPLOY_ENV" == staging ]]; then
    echo "STAGING ONLY: no paid Prolific recruitment and no production completion codes."
  fi
else
  printf 'Planned left-only DTAG URL: %s/study\n' "$DTAG_PUBLIC_ORIGIN"
fi
