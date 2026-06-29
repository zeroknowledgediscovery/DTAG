#!/usr/bin/env bash
set -euo pipefail
EXP=${1:-gss2022_master}
shift || true
python3 scripts/post.py --config configs/dtag_config.yaml --experiment "$EXP" "$@"
