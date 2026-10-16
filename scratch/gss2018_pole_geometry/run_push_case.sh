#!/usr/bin/env bash
# Run ONE push experiment locally (one persona, one direction), then rebuild the summary.
#
#   bash scratch/gss2018_pole_geometry/run_push_case.sh CM right
#   bash scratch/gss2018_pole_geometry/run_push_case.sh WF left --steps 4 --runs 2
#
# Positional: PERSONA (CM|WF)  DIRECTION (right|left). Any further flags are passed to
# greedy_push_runs.py (defaults below match the documented experiment). Run from anywhere.
# First run builds the native binding if needed and downloads gss/gss_2018 (~public release).
# Cost: ~1 min per greedy step on a 4-core machine; default case ~20-25 min. Run cases one at
# a time: the native runtime is multi-threaded, so parallel cases mostly slow each other down.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PERSONA="${1:?usage: run_push_case.sh CM|WF right|left [extra flags]}"
DIRECTION="${2:?usage: run_push_case.sh CM|WF right|left [extra flags]}"
shift 2
PY="${PYTHON:-python3}"

if ! "$PY" -c "import sys; sys.path.insert(0,'native/lsm_runtime/python'); import dtag_lsm" 2>/dev/null; then
  echo "Building native DTAG LSM binding ..."
  bash scripts/build_native_bindings.sh
fi
"$PY" scripts/fetch_models.py gss/gss_2018    # no-op when already installed

LOG="scratch/gss2018_pole_geometry/greedy_runs/${PERSONA}_${DIRECTION}.log"
mkdir -p "$(dirname "$LOG")"
echo "Running $PERSONA -> $DIRECTION (log: $LOG)"
"$PY" -u scratch/gss2018_pole_geometry/greedy_push_runs.py \
  --persona "$PERSONA" --direction "$DIRECTION" \
  --steps 6 --runs 3 --baseline-runs 30 --pool 120 --audit "$@" 2>&1 | tee "$LOG"

"$PY" scratch/gss2018_pole_geometry/greedy_runs_summary.py > /dev/null
echo "Done. Per-step CSV: scratch/gss2018_pole_geometry/greedy_runs/${PERSONA}_${DIRECTION}.csv"
echo "Summary of all finished cases: scratch/gss2018_pole_geometry/greedy_runs/summary.md"
