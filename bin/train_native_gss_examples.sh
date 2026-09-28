#!/usr/bin/env bash
set -euo pipefail

# Train the first DTAG native-LSM validation set:
#   gss_2018.csv
#   gss_2022.csv
#   gss_2024.csv
#
# Usage:
#   LSM_BIN=/path/to/lsm/bin/LSM bin/train_native_gss_examples.sh /path/to/gss
#
# If the CSVs are in the current directory:
#   LSM_BIN=/path/to/lsm/bin/LSM /path/to/DTAG/bin/train_native_gss_examples.sh .

DATA_DIR="${1:-.}"
shift || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 "$ROOT/scripts/train_native_lsm_models.py" "$DATA_DIR"   --model gss_2018   --model gss_2022   --model gss_2024   "$@"
