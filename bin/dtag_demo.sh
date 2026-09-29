#!/usr/bin/env bash
# End-to-end DTAG validation and demonstration driver.
#
# Default mode is deterministic/no-LLM and is safe for CI/development.
# Add --openai to run one live question through each supported survey family.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_OPENAI=0
QUICK=0
QUESTION="How satisfied are you with the way democracy works?"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --openai)
      RUN_OPENAI=1
      shift
      ;;
    --quick)
      QUICK=1
      shift
      ;;
    --question)
      QUESTION="${2:?--question requires text}"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage: bin/dtag_demo.sh [--quick] [--openai] [--question TEXT]

Default:
  Runs deterministic/native validation without calling an LLM.

--quick:
  Skips the full readiness and Eurobarometer inventory audits.

--openai:
  Adds one live end-to-end question for:
    GSS 2024 native
    WVS7 native / India
    Afrobarometer R5 native / Nigeria
    Eurobarometer exact-codebook wave selected by date/place
    Eurobarometer union-fallback wave selected by ZA/place

Environment:
  LSM_BINDINGS_DIR  directory containing native LSM Python bindings
  OPENAI_API_KEY    required only with --openai
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

section() {
  printf '\n================================================================\n'
  printf '%s\n' "$1"
  printf '================================================================\n'
}

run() {
  echo "+ $*"
  "$@"
}

section "DTAG environment"
echo "root: $ROOT"
echo "python: $(command -v python3)"
python3 --version
echo "LSM_BINDINGS_DIR: ${LSM_BINDINGS_DIR:-<not set>}"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY: set"
else
  echo "OPENAI_API_KEY: not set"
fi

section "Python syntax"
run python3 -m py_compile scripts/*.py

section "Native model inventory"
run python3 scripts/inventory_native_models.py

section "Native repository cleanup audit"
run python3 scripts/audit_clean_repo.py --allow-local-legacy

section "Complete model/map overlap audit"
run python3 scripts/audit_native_maps.py --deep

section "Native backend contract tests"
run python3 scripts/test_native_lsm_dtag.py

section "Country-conditioning regression"
run python3 scripts/test_country_conditioning.py

if [[ "$QUICK" -eq 0 ]]; then
  section "Repository readiness"
  run python3 scripts/check_dtag_readiness.py --create-smoke-csv --overlap

  section "Eurobarometer model/map audit"
  run python3 scripts/audit_eurobarometer_assets.py
fi

section "Config/profile discovery"
run bin/interactive_config.sh --list
run bin/list_experiments.sh

section "Dry-run native interactive profiles"
run bin/interactive_config.sh \
  --profile gss2024_cm \
  --question "$QUESTION" \
  --print-command

run bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --question "$QUESTION" \
  --print-command

run bin/interactive_config.sh \
  --profile afrobarometer_r5_nigeria \
  --question "$QUESTION" \
  --print-command

section "Eurobarometer time/place routing demos"
run python3 scripts/eurobarometer_native.py \
  --date 2019-05-15 \
  --country France \
  --question "$QUESTION" \
  --print-command

run python3 scripts/eurobarometer_native.py \
  --za ZA8843 \
  --country France \
  --question "$QUESTION" \
  --print-command

if [[ "$RUN_OPENAI" -eq 1 ]]; then
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: --openai requires OPENAI_API_KEY" >&2
    exit 2
  fi

  section "LIVE DEMO: GSS 2024 native"
  run bin/interactive_config.sh \
    --profile gss2024_cm \
    --question "$QUESTION"

  section "LIVE DEMO: WVS7 native / India"
  run bin/interactive_config.sh \
    --profile wvs7_india_2017 \
    --question "$QUESTION"

  section "LIVE DEMO: Afrobarometer R5 native / Nigeria"
  run bin/interactive_config.sh \
    --profile afrobarometer_r5_nigeria \
    --question "$QUESTION"

  section "LIVE DEMO: Eurobarometer exact date/place"
  run python3 scripts/eurobarometer_native.py \
    --date 2019-05-15 \
    --country France \
    --question "$QUESTION"

  section "LIVE DEMO: Eurobarometer fallback ZA/place"
  run python3 scripts/eurobarometer_native.py \
    --za ZA8843 \
    --country France \
    --question "$QUESTION"
fi

section "DTAG demo/test complete"
echo "Structural/native tests completed successfully."
if [[ "$RUN_OPENAI" -eq 0 ]]; then
  echo "Live LLM calls were not run. Re-run with --openai to exercise answer generation."
fi
