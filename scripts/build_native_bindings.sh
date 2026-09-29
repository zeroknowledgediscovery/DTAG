#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/native/lsm_runtime"
BUILD="$SRC/build"
PYDIR="$SRC/python"
JOBS="${DTAG_BUILD_JOBS:-$(nproc 2>/dev/null || echo 4)}"

PYTHON_BIN="$(command -v python3)"

# Reconfigure from a clean build tree so an older OpenMP-linked build cannot
# survive in the CMake cache.
rm -rf "$BUILD"
mkdir -p "$PYDIR"
rm -f "$PYDIR"/dtag_lsm*.so

cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DPython_EXECUTABLE="$PYTHON_BIN" \
  -DPYTHON_EXECUTABLE="$PYTHON_BIN"

cmake --build "$BUILD" --parallel "$JOBS"

SO="$(find "$PYDIR" -maxdepth 1 -type f -name 'dtag_lsm*.so' -print -quit)"
if [[ -z "$SO" || ! -f "$SO" ]]; then
  echo "ERROR: bundled dtag_lsm shared object was not produced." >&2
  exit 1
fi

echo
echo "Built extension:"
file "$SO" || true

if command -v ldd >/dev/null 2>&1; then
  echo
  echo "Dynamic dependencies:"
  DEPS="$(ldd "$SO")"
  echo "$DEPS"

  if grep -Eq 'libgomp|libstdc\+\+|libgcc_s' <<<"$DEPS"; then
    echo >&2
    echo "ERROR: extension still has a dynamic compiler/OpenMP runtime dependency." >&2
    echo "Expected no libgomp, libstdc++.so, or libgcc_s.so dependency." >&2
    exit 1
  fi

  echo
  echo "PASS: no dynamic libgomp/libstdc++/libgcc_s dependency."
fi

PYTHONPATH="$PYDIR:${PYTHONPATH:-}" "$PYTHON_BIN" - <<'PY'
import dtag_lsm
print("DTAG native LSM binding:", dtag_lsm.__file__)
print("Runtime class:", dtag_lsm.Runtime)
PY

echo
echo "Built bundled DTAG native LSM runtime."
echo "LSM runtime code, libstdc++, and libgcc are contained in the extension."
echo "The host CPython/glibc ABI remains external."
echo "No sibling LSM repository is required at runtime."
