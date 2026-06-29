#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
EXP="${1:-gss2022_divergence}"
shift || true
python3 scripts/post.py --config configs/dtag_config.yaml --experiment "$EXP" "$@"
