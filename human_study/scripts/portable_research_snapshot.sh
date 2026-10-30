#!/usr/bin/env bash
# Preserve/recover the Oct 30 2026 DTAG human-study analysis on another machine.
#
# Files go to the PRIVATE research GCS bucket; the HMAC key goes ONLY to GCP
# Secret Manager, never into the bucket/repository. Requires gcloud and Python3.
#
# BACKUP (once, on the original workstation, after generating trajectories):
#  export DTAG_DEM_PDF=/absolute/private/path/DEMOCRATIC_recruitment...pdf
#  export DTAG_REP_PDF=/absolute/private/path/REPUBLICAN_RECRUIOT...pdf
#  bash human_study/scripts/portable_research_snapshot.sh backup
#
# RESTORE (fresh machine, after git clone and gcloud auth login):
#  bash human_study/scripts/portable_research_snapshot.sh restore
#
# Override snapshot ID or default paths with DTAG_SNAPSHOT_ID,
# DTAG_AUDIT_DIR, DTAG_ANALYSIS_DIR, DTAG_TRAJECTORIES_DIR,
# DTAG_Q4_DIR, DTAG_KEY_FILE, DTAG_RESTORE_DIR.
set -euo pipefail
umask 077
mode="${1:-}"
if [[ "$mode" != backup && "$mode" != restore ]]; then
  echo "Usage: bash $0 backup|restore" >&2
  exit 2
fi

project="pkcsaas-01"
bucket="gs://pkcsaas-01-dtag-study-data"
secret="dtag-private-analysis-hmac-2026"
snap="${DTAG_SNAPSHOT_ID:-2026-10-30-restored-v1}"
if [[ ! "$snap" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Invalid snapshot ID" >&2; exit 2
fi
remote="$bucket/private-analysis/reproducibility/$snap/snapshot"
home="$HOME/private"
key="${DTAG_KEY_FILE:-$HOME/.config/dtag/private_analysis_hmac_key.bin}"

require_command() { command -v "$1" >/dev/null || { echo "Missing command $1" >&2; exit 2; }; }
require_command gcloud
require_command python3
require_command sha256sum
require_command git
mkdir -p "$home"
chmod 700 "$home"

check_bucket() {
  local meta
  meta="$(gcloud storage buckets describe "$bucket" --format=json)"
  printf '%s' "$meta" | python3 -c '
import sys, json
d=json.load(sys.stdin)
iam=d.get("iamConfiguration",{})
pap=iam.get("publicAccessPrevention")
uba=iam.get("uniformBucketLevelAccess",{}).get("enabled")
if pap!="enforced" or uba is not True:
    raise SystemExit("STOP: Research GCS bucket lacks enforced public-access prevention or uniform bucket-level access")
print("Research GCS bucket: public access prevention enforced; uniform bucket access enabled")
'
}
check_bucket

if [[ "$mode" == backup ]]; then
  audit="${DTAG_AUDIT_DIR:-/tmp/dtag_full_audit}"
  analysis="${DTAG_ANALYSIS_DIR:-$home/dtag-analysis-2026-10-30-restored}"
  traj="${DTAG_TRAJECTORIES_DIR:-$home/dtag-trajectories-2026-10-30-restored}"
  q4="${DTAG_Q4_DIR:-$home/dtag-q4-resistance-restored}"
  dem="${DTAG_DEM_PDF:-}"
  rep="${DTAG_REP_PDF:-}"

  for path in "$audit/PRIVATE_all_sessions.csv" "$audit/PRIVATE_participant_crosswalk.csv" \
      "$analysis/sessions.csv" "$analysis/steps.csv" "$analysis/manifest.json" \
      "$traj/trajectories_wide_PRIVATE.csv" "$traj/trajectories_long_PRIVATE.csv" \
      "$traj/trajectory_manifest_PRIVATE.json" \
      "$q4/q4_resistance_table.csv" "$q4/q4_resistance_diagnostics.json" \
      "$key" "$dem" "$rep"; do
    if [[ -z "$path" || ! -f "$path" || -L "$path" ]]; then
      echo "STOP: missing or symlinked required file: $path" >&2
      echo "Pass the two private roster PDF paths via DTAG_DEM_PDF/DTAG_REP_PDF." >&2
      exit 2
    fi
  done
  if [[ $(wc -c < "$key") -lt 32 ]]; then
    echo "STOP: pseudonymization key shorter than 32 bytes" >&2; exit 2
  fi
  # Validate the restored study counts before making any cloud changes.
  python3 - "$analysis/sessions.csv" "$q4/q4_resistance_table.csv" <<'PY'
import csv,sys
with open(sys.argv[1],newline="") as f: rows=list(csv.DictReader(f))
complete=[x for x in rows if x.get("complete_20_archive","").lower()=="true"]
prod={"prolific-v3-human-opinions-2026-10","prolific-v3-left-followup-2026-10","prolific-v3-right-followup-2026-10","dtag-v3-nocal-right-2026-10"}
complete=[x for x in complete if x.get("dtag_study_id") in prod]
assert len(complete)==102, f"Expected 102 verified production completions; got {len(complete)}"
cal=[x for x in complete if x.get("protocol")=="six_question_calibration" and x.get("policy") in ("left","right")]
assert len(cal)==59, f"Expected 59 calibrated directional sessions; got {len(cal)}"
with open(sys.argv[2],newline="") as f: q4=list(csv.DictReader(f))
overall=next(x for x in q4 if x.get("initial_phenotype")=="Overall")
assert (int(overall["left_n"]),int(overall["right_n"]))==(21,38)
assert (int(overall["left_directional_success"]),int(overall["right_directional_success"]))==(20,21)
assert int(overall["right_extended_success"])==38
print("Scientific totals verified: 102 archived production; calibrated Left 21, Right 38; Q4 extended Right 38/38")
PY
  # Do not overwrite an existing cloud snapshot.
  if gcloud storage ls "$remote/SHA256SUMS.txt" >/dev/null 2>&1; then
    echo "STOP: snapshot already exists: $remote" >&2; exit 2
  fi
  # Store exact binary key in Secret Manager, NOT Cloud Storage.
  if gcloud secrets describe "$secret" --project="$project" --format=json >/dev/null 2>&1; then
    keycheck="$(mktemp "$home/.dtag-key-verify.XXXXXXXX")"
    trap 'rm -f "$keycheck"' EXIT
    gcloud secrets versions access latest --secret="$secret" --project="$project" --out-file="$keycheck"
    if ! cmp -s "$key" "$keycheck"; then
      echo "STOP: Secret Manager key differs from local key. Do not replace or rotate." >&2
      exit 2
    fi
    rm -f "$keycheck"
    trap - EXIT
    echo "Secret Manager: existing exact key verified"
  else
    # Never interpret an authorization error as permission to overwrite an
    # existing secret: create fails atomically if it exists.
    gcloud secrets create "$secret" --project="$project" \
      --replication-policy=automatic --data-file="$key"
    echo "Secret Manager: private HMAC key securely stored"
  fi
  staging="$(mktemp -d "$home/.dtag-portable.XXXXXXXX")"
  trap 'rm -rf "$staging"' EXIT
  mkdir -p "$staging/snapshot/rosters"
  cp -a "$audit" "$staging/snapshot/audit"
  cp -a "$analysis" "$staging/snapshot/analysis"
  cp -a "$traj" "$staging/snapshot/trajectories"
  cp -a "$q4" "$staging/snapshot/q4"
  cp "$dem" "$staging/snapshot/rosters/democratic_approved_payment.pdf"
  cp "$rep" "$staging/snapshot/rosters/republican_approved_payment.pdf"
  gitroot="$(git rev-parse --show-toplevel)"
  revision="$(git -C "$gitroot" rev-parse HEAD)"
  key_sha="$(sha256sum "$key" | cut -d' ' -f1)"
  python3 - "$staging/snapshot" "$revision" "$key_sha" "$snap" <<'PY'
import json,sys
from pathlib import Path
from datetime import datetime, timezone
p=Path(sys.argv[1])
obj={"schema_version":1,"created_utc":datetime.now(timezone.utc).isoformat(),
     "snapshot_id":sys.argv[4],"git_checkout_commit":sys.argv[2],
     "git_branch_required":"experiment/prolific-human-study",
     "gcp_project":"pkcsaas-01",
     "source_gcs_bucket":"pkcsaas-01-dtag-study-data",
     "source_firestore_database":"dtag-human-pilot",
     "pseudonymization_secret":"dtag-private-analysis-hmac-2026",
     "pseudonymization_key_sha256":sys.argv[3],
     "production_20_answer_sessions":102,
     "calibrated_left_right":59,
     "status":"Investigator-reported restored 2026-10-30 analysis freeze",
     "sensitive":"All bundled files PRIVATE. Do not push to Git."}
(p/"snapshot_provenance.json").write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
PY
  (
    cd "$staging/snapshot"
    find . -type l | grep . && { echo "STOP: symlink in staged snapshot" >&2; exit 2; } || true
    find . -type f ! -name SHA256SUMS.txt -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS.txt
    sha256sum -c SHA256SUMS.txt >/dev/null
  )
  echo "Uploading new private GCS reproducibility snapshot: $remote"
  gcloud storage cp --recursive --if-generation-match=0 "$staging/snapshot" \
    "$bucket/private-analysis/reproducibility/$snap/"
  gcloud storage cp "$remote/SHA256SUMS.txt" "$staging/uploaded-SHA256SUMS.txt"
  cmp "$staging/snapshot/SHA256SUMS.txt" "$staging/uploaded-SHA256SUMS.txt"
  echo "UPLOADED: snapshot manifest matches local checksums."
  echo "Cloud URL: $remote"
  echo "Run restore on a different machine to verify all object bytes."
else
  dest="${DTAG_RESTORE_DIR:-$home/dtag-portable-$snap}"
  if [[ -e "$dest" ]]; then
    echo "STOP: restore directory exists: $dest" >&2; exit 2
  fi
  mkdir -m 700 "$dest"
  echo "Downloading private snapshot into $dest"
  gcloud storage cp --recursive "$remote" "$dest/"
  manifest="$(find "$dest" -type f -name SHA256SUMS.txt -print -quit)"
  if [[ -z "$manifest" ]]; then
    echo "STOP: no checksum manifest in downloaded snapshot" >&2; exit 2
  fi
  root="$(dirname "$manifest")"
  (
    cd "$root"
    sha256sum -c SHA256SUMS.txt
  )
  # Make downloaded records private even if local default file modes differ.
  chmod -R go-rwx "$dest"
  expected="$(python3 - "$root/snapshot_provenance.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))["pseudonymization_key_sha256"])
PY
)"
  if [[ -e "$key" ]]; then
    actual="$(sha256sum "$key" | cut -d' ' -f1)"
    if [[ "$actual" != "$expected" ]]; then
      echo "STOP: local HMAC key differs from backed-up data" >&2; exit 2
    fi
  else
    mkdir -p "$(dirname "$key")"
    chmod 700 "$(dirname "$key")"
    gcloud secrets versions access latest --secret="$secret" --project="$project" --out-file="$key"
    chmod 600 "$key"
    actual="$(sha256sum "$key" | cut -d' ' -f1)"
    if [[ "$actual" != "$expected" ]]; then
      rm -f "$key"
      echo "STOP: restored HMAC key hash mismatch" >&2; exit 2
    fi
  fi
  echo "RESTORED and verified every bundled file: $root"
  echo "HMAC key recovered/verified privately: $key"
  echo "Use the saved snapshot_provenance.json git revision and run Q4 on $root/analysis"
fi
