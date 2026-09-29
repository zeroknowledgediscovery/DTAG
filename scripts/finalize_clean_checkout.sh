#!/usr/bin/env bash
# Finalize a native-lsm-clean checkout after map generation.
set -euo pipefail

ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY=0
if [[ "\${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--apply]" >&2
  exit 2
fi

branch="$(git branch --show-current)"
if [[ "$branch" != "native-lsm-clean" ]]; then
  echo "ERROR: expected branch native-lsm-clean, found: $branch" >&2
  exit 1
fi

echo "== Native asset audit =="
python3 scripts/audit_native_maps.py --deep

count_gss="$(find maps/gss -maxdepth 1 -type f -name 'gss_*_map.csv' | wc -l)"
count_afro="$(find maps/afromap -maxdepth 1 -type f -name 'afrobarometer_r*_map.csv' | wc -l)"
count_euro="$(find maps/eurobarometer -maxdepth 1 -type f -name 'ZA*_map.csv' | wc -l)"
count_wvs=0
[[ -f maps/wvs7_variable_question_map.csv ]] && count_wvs=1

echo
echo "Canonical map counts:"
echo "  GSS:           $count_gss / 35"
echo "  Afrobarometer: $count_afro / 9"
echo "  WVS:           $count_wvs / 1"
echo "  Eurobarometer: $count_euro / 207"

if [[ "$count_gss" -ne 35 || "$count_afro" -ne 9 || "$count_wvs" -ne 1 || "$count_euro" -ne 207 ]]; then
  echo "ERROR: canonical map counts are incomplete; refusing to stage/clean." >&2
  exit 1
fi

echo
echo "== Known local legacy residues =="
legacy=(
  "models/gss"
  "maps/map2022.csv"
  "maps/map2024.csv"
  "maps/map.csv"
  "maps/map20162020.csv"
  "maps/afromap/afrobaromete_r1_map.csv"
  "bin/complete_native_models.sh"
)

for p in "\${legacy[@]}"; do
  if [[ -e "$p" ]]; then
    if [[ "$APPLY" -eq 1 ]]; then
      echo "REMOVE $p"
      rm -rf -- "$p"
    else
      echo "WOULD REMOVE $p"
    fi
  fi
done

echo
echo "== Stage canonical maps =="
git add \
  maps/gss/*.csv \
  maps/afromap/afrobarometer_r*_map.csv \
  maps/eurobarometer/ZA*_map.csv \
  maps/wvs7_variable_question_map.csv \
  maps/README.md

echo
echo "Staged map summary:"
git diff --cached --stat -- maps

echo
echo "Untracked/modified remainder:"
git status --short

if [[ "$APPLY" -eq 0 ]]; then
  echo
  echo "Dry run cleanup only. Re-run with --apply after reviewing the listed residues."
else
  echo
  echo "Known-safe legacy residues removed. Canonical maps are staged."
  echo "Review 'git status', then commit/push the map corpus."
fi
