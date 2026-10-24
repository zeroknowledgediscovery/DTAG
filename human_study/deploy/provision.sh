#!/usr/bin/env bash
# Defaults to printing commands. --execute creates billable GCP resources.
set -euo pipefail
EXECUTE=0
[[ "${1:-}" != --execute ]] || EXECUTE=1
: "${GCP_PROJECT:?Set an isolated, billing-enabled project ID}"
: "${DTAG_GCS_BUCKET:?Set a globally unique PRIVATE bucket name}"
REGION="${GCP_REGION:-us-east1}"
DATABASE="${DTAG_FIRESTORE_DATABASE:-(default)}"
APP_SA="dtag-study@${GCP_PROJECT}.iam.gserviceaccount.com"
BUILD_SA="dtag-build@${GCP_PROJECT}.iam.gserviceaccount.com"
run() { if [[ "$EXECUTE" == 1 ]]; then "$@"; else printf '%q ' "$@"; printf '\n'; fi; }
run gcloud services enable run.googleapis.com firestore.googleapis.com storage.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com iam.googleapis.com --project "$GCP_PROJECT"
run gcloud iam service-accounts create dtag-study --display-name 'DTAG participant service' --project "$GCP_PROJECT"
run gcloud iam service-accounts create dtag-build --display-name 'DTAG image builder' --project "$GCP_PROJECT"
run gcloud firestore databases create --database "$DATABASE" --location "$REGION" --type firestore-native --project "$GCP_PROJECT"
run gcloud storage buckets create "gs://$DTAG_GCS_BUCKET" --location "$REGION" --uniform-bucket-level-access --public-access-prevention --project "$GCP_PROJECT"
run gcloud storage buckets update "gs://$DTAG_GCS_BUCKET" --versioning --project "$GCP_PROJECT"
run gcloud iam roles create dtagArchive --project "$GCP_PROJECT" --title 'DTAG immutable archive access' --stage GA --permissions storage.buckets.get,storage.objects.create,storage.objects.get,storage.objects.list
run gcloud storage buckets add-iam-policy-binding "gs://$DTAG_GCS_BUCKET" --member "serviceAccount:$APP_SA" --role "projects/$GCP_PROJECT/roles/dtagArchive"
run gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$APP_SA" --role roles/datastore.user
run gcloud artifacts repositories create dtag-study --repository-format docker --location "$REGION" --project "$GCP_PROJECT"
run gcloud artifacts repositories add-iam-policy-binding dtag-study --location "$REGION" --member "serviceAccount:$BUILD_SA" --role roles/artifactregistry.writer --project "$GCP_PROJECT"
run gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$BUILD_SA" --role roles/logging.logWriter
# Cloud Build source staging uses its project build bucket; scope these roles to it after first creation.
run gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member "serviceAccount:$BUILD_SA" --role roles/storage.objectViewer
for secret in dtag-cookie-secret dtag-openai-api-key; do
  run gcloud secrets create "$secret" --replication-policy automatic --project "$GCP_PROJECT"
  run gcloud secrets add-iam-policy-binding "$secret" --member "serviceAccount:$APP_SA" --role roles/secretmanager.secretAccessor --project "$GCP_PROJECT"
done
printf '%s\n' 'No secret versions are created by this script. Supply values securely in Secret Manager before deployment.'
printf '%s\n' 'The deploying investigator also needs iam.serviceAccounts.actAs on the build and runtime service accounts.'
