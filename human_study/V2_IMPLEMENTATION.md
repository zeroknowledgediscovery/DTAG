# Human Study V2 — LLM-generated questions and open-text responses

Status: **implemented in code and tests; not yet deployed or approved for participants**.
V2 uses a separate `pilot-v2` instrument and does not alter any prior
`pilot-001` Firestore records or immutable GCS archives.

## Exactly seven questions in the short internal pilot

`human_study/config/study.v2.example.yaml` specifies:

- `initial_steps: 4`, with baseline variables `trust`, `fair`, `helpful`,
  and `health` presented in that order.
- `intervention_steps: 3`, chosen by the existing left/right/neutral/random
  native DTAG one-step geometry policy from a curated 17-item intervention bank.
- No outcome questions in this short technical study, so there are **7** total.
- `question_mode: llm_required`: **every question, including initial questions,
  must be successfully rephrased by the live OpenAI provider.** A blank answer,
  source-text fallback, unchanged source, or a failed semantic validation stops
  that question and raises a retryable generation failure. We do **not** silently
  display raw map text or bypass question generation.
- `response_mode: free_text_llm`: a textarea is presented in place of radio
  buttons. Categories are retained internally for the LSM but are not clickable.

The baseline length is controlled by `initial_steps`, which selects the
first N `baseline` items in the configured bank. The intervention length is
controlled independently by `intervention_steps`. Increase either by
supplying sufficient reviewed items in the respective banks; native candidate
eligibility is checked against the requested adaptive length.

## Interpretation contract and fail-closed behavior

Each written answer (max 2,000 characters) is sent with the **exact displayed
question** and **the item's native categories** to OpenAI using structured
JSON output. The LLM must return `mapped`, `missing`, or `ambiguous`, plus
a native category and confidence score. The native category is accepted only
if it is **one of the configured/model-supported values** and the confidence
is at least `minimum_mapping_confidence` (currently `0.80`).

When the answer is ambiguous, off-scale, or low-confidence, the request is
rejected with HTTP 422 and the participant can edit their prose. No native
LSM observation is added. A provider outage returns HTTP 503, keeps the
existing answer and idempotency key, and can be retried without advancing.

When the participant explicitly declines, a model-classified `missing`
response may be recorded as missingness on optional items; it is **not**
invented as a category or drawn from the native conditional distribution.

Accepted records store **both** `raw_text_response` and
`response_interpretation` (native category, confidence, model, status,
and rationale), as well as the original source, generated wording,
scientific selection, and optional conditional-index result. All go through
the existing transactional Firestore/GCS audit and immutable `final.json`.
Raw text is visible to investigators in the private archive, not public APIs.

## Validation and deployment

Run from the repository root:

```bash
git pull --ff-only
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 -m pytest -q \
  human_study/tests/test_v2_written_responses.py \
  human_study/tests/test_human_engine.py \
  human_study/tests/test_human_api.py \
  human_study/tests/test_persistence.py \
  human_study/tests/test_cloud_adapters.py
```

The tracked YAML remains `reviewed: false`. For an internal live test,
**inspect and approve all source questions and native answer labels**, then
write a separate externally stored copy and set `reviewed: true` on that
reviewed copy only. Example:

```bash
mkdir -p "$HOME/.config/dtag-study"
cp human_study/config/study.v2.example.yaml "$HOME/.config/dtag-study/pilot-v2-reviewed.yaml"
# Inspect/edit this file, then explicitly set reviewed: true only after review.
export DTAG_REVIEWED_CONFIG="$HOME/.config/dtag-study/pilot-v2-reviewed.yaml"
# Existing DTAG_GCS_BUCKET, GCP_PROJECT, GCP_REGION, DTAG_PUBLIC_ORIGIN
# and DTAG_FIRESTORE_DATABASE deployment settings are reused.
bash human_study/deploy/deploy.sh
# Run with --execute only after reviewing the dry-run output and tests.
```

`pilot-v2` uses distinct immutable study storage from `pilot-001`.
Use a fresh private browsing window for the new version, since previous
browser cookies refer to a different study/session.

## Research caveats and V3

This is an **internal engineering pilot only**. The curated candidate pool
excludes known ranking and unanchored numeric-response items, but the
remaining partial 2024 GSS stems and form variants have **not all been
independently certified against the official source questionnaires**.
Neither LLM rewording nor reverse mapping alone establishes measurement
invariance. Before Prolific recruitment, validate all included text, scales,
and state transitions with reviewed 2024 source material and complete a
seven-question live end-to-end test.

Attention/comprehension checks are deliberately deferred to **V3**.
