#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/native/lsm_runtime"
BUILD="$SRC/build"
JOBS="${DTAG_BUILD_JOBS:-$(nproc 2>/dev/null || echo 4)}"

PYTHON_BIN="$(command -v python3)"

cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython_EXECUTABLE="$PYTHON_BIN" \
  -DPYTHON_EXECUTABLE="$PYTHON_BIN"
cmake --build "$BUILD" --parallel "$JOBS"

PYTHONPATH="$SRC/python:${PYTHONPATH:-}" python3 - <<'PY'
import dtag_lsm
print("DTAG native LSM binding:", dtag_lsm.__file__)
print("Runtime class:", dtag_lsm.Runtime)
PY

echo
echo "Built bundled DTAG native LSM runtime."
echo "No sibling LSM repository is required at runtime."
