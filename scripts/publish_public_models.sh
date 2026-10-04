#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RELEASE="${1:-v0.2.1}"
MODE="${2:-}"
BUCKET="${DTAG_PUBLIC_BUCKET:-git-zeroknowledgediscovery-dtag}"
MODEL_ROOT="${DTAG_MODEL_ROOT:-$ROOT/models/lsm}"
OUT="${DTAG_RELEASE_DIR:-/tmp/dtag-models-$RELEASE}"
LOCATION="${DTAG_GCS_LOCATION:-US}"

command -v gcloud >/dev/null 2>&1 || {
  echo "ERROR: gcloud CLI is required." >&2
  exit 1
}

if [[ "$MODE" == "--existing" ]]; then
  echo "== Rebuild manifest for existing tar.zst release =="
  python3 scripts/rebuild_public_manifest.py "$OUT" \
    --release "$RELEASE" \
    --bucket "$BUCKET"
else
  echo "== Package runtime-only model release =="
  python3 scripts/package_public_models.py \
    --model-root "$MODEL_ROOT" \
    --release "$RELEASE" \
    --bucket "$BUCKET" \
    --out "$OUT"
fi

echo
echo "== Local release size =="
du -sh "$OUT"

echo
echo "== Ensure bucket exists =="
if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" --location="$LOCATION"
else
  echo "Bucket already exists: gs://$BUCKET"
fi

echo
echo "== Allow public access on bucket =="
gcloud storage buckets update "gs://$BUCKET" --no-public-access-prevention

gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member=allUsers \
  --role=roles/storage.objectViewer

echo
echo "== Upload release =="
gcloud storage rsync --recursive \
  "$OUT" \
  "gs://$BUCKET/models/$RELEASE"

MANIFEST_URL="https://storage.googleapis.com/$BUCKET/models/$RELEASE/manifest.json"

echo
echo "== Verify anonymous manifest access =="
python3 - "$MANIFEST_URL" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=30) as r:
    body = r.read()
    print("HTTP:", r.status)
    print("bytes:", len(body))
    if r.status != 200:
        raise SystemExit(1)
PY

echo
echo "PASS: public DTAG model release published"
echo "Bucket:   gs://$BUCKET/models/$RELEASE"
echo "Manifest: $MANIFEST_URL"
