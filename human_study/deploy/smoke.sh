#!/usr/bin/env bash
# Read-only probes only. Run after an authorized deployment, with its actual URL.
set -euo pipefail
: "${STUDY_URL:?Set the actual HTTPS Cloud Run service URL}"
[[ "$STUDY_URL" == https://* ]] || exit 1
curl --fail --silent --show-error "$STUDY_URL/api/human/health"
curl --fail --silent --show-error "$STUDY_URL/api/human/readiness"
curl --fail --silent --show-error --output /dev/null "$STUDY_URL/study"
