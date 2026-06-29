#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
EXP="${1:-gss2022_divergence}"
python3 scripts/run.py --config configs/dtag_config.yaml --experiment "$EXP"
