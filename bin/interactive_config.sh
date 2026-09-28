#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DTAG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DTAG_ROOT"
exec python3 scripts/interactive.py --config configs/dtag_config.yaml "$@"
