#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/interactive.py --config configs/dtag_config.yaml "$@"
