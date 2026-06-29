#!/usr/bin/env bash
set -euo pipefail
python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_master "$@"
