#!/usr/bin/env bash
# One-command offline V3 verification: uses synthetic responses and in-memory
# repository/archive. NO OpenAI calls, GCP writes, recruitment or live sessions.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT/human_study/backend:$ROOT/scripts:$ROOT"
export DTAG_ENV=local
unset DTAG_STUDY_CONFIG DTAG_REVIEWED_CONFIG DTAG_PUBLIC_ORIGIN || true

echo "[1/3] V3 short, interleaved, 6+20+5 sessions and webapp parity"
python3 -m pytest -q -rs \
  human_study/tests/test_v3_multi_observations.py \
  human_study/tests/test_v3_question_referents.py \
  human_study/tests/test_grounded_question_generation.py \
  human_study/tests/test_compiled_wording.py \
  human_study/tests/test_standalone_candidate_audit.py \
  human_study/tests/test_full_native_gss_audit.py \
  human_study/tests/test_question_archive_audit.py \
  human_study/tests/test_v3_schedule_and_simulation.py \
  human_study/tests/test_v3_trajectory_analysis.py \
  human_study/tests/test_webapp_parity.py \
  human_study/tests/test_native_webapp_service.py \
  human_study/tests/test_v3_zero_baseline.py \
  human_study/tests/test_push_phenotypes.py \
  human_study/tests/test_prolific_study.py \
  human_study/tests/test_quality_review.py \
  human_study/tests/test_rejection_eligibility.py

echo "[wording audit] GSS 2024 map and source-grounded contracts"
python3 human_study/scripts/audit_gss_wording_map.py --check

echo "[wider audit] Static native opinion-screening labels (read-only)"
python3 human_study/scripts/audit_standalone_candidates.py --compact

echo "[2/3] Existing answer, persistence, and cloud adapter regression"
python3 -m pytest -q -rs \
  human_study/tests/test_v2_written_responses.py \
  human_study/tests/test_human_api.py \
  human_study/tests/test_persistence.py \
  human_study/tests/test_cloud_adapters.py \
  human_study/tests/test_firestore_parallel_read.py

echo "[3/3] Frontend type-check and production bundle"
(cd human_study/frontend && npm run build)

echo "PASS: Offline V3 regression and scripted full sessions completed."
echo "NOTE: synthetic adapter/LLM are NOT evidence of real model or provider reliability."
