#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL="${1:-gpt-4.1-mini}"
python3 scripts/smoke_test.py --model "$MODEL"
