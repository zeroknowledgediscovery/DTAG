#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
EXP="${1:-gss2022_divergence}"
# Temporarily override by calling the core postprocessor directly after config-based paths are known.
# For most cases, edit configs/dtag_config.yaml and set quadrant_variant: all.
python3 scripts/post.py --config configs/dtag_config.yaml --experiment "$EXP"
