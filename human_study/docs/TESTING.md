# V3 human-study verification plan

**Goal:** test the complete participant/session/state/archive pipeline without
hand-entering answers on every change, and explicitly distinguish *offline
software correctness* from *real LLM/native model/scientific validity*.

## A. One-command fully offline regression (no API keys or GCP)

From the DTAG repository root:

```bash
git pull --ff-only
bash human_study/scripts/check_v3.sh
```

This script uses pytest, the deterministic test LLM, in-memory Firestore/GCS
equivalents, and the independent synthetic adapter in
`tests/conftest.py`. It does **not** send human data or call OpenAI.
It checks:

- All V3 original 4+3 cases, multi-coordinate initial states,
  conflicts/confirmations, native-label/evidence validation and LSM replay.
- Fully synthetic end-to-end sessions with attention at counts
  `[0,2,4,5,7]`: before baseline, mid-baseline, after baseline,
  during the adaptive sequence, after the last substantive question.
- Adjacent attention checks with the same substantive position.
- A 6-baseline/20-adaptive/5-attention long synthetic session
  (31 screens, 20 native scoring/selection steps) using
  `[3,8,13,18,24]` as attention positions.
- Idempotent answer reposts at multiple boundaries. Reposts never
  introduce additional observations or change question counts.
- Archived `final.json`, deterministic replay, and persistent attention
  results; attention must not change the native state.
- V2 compatibility, API boundary checks, storage/outbox
  fault-injection tests and the React/TypeScript production build.

These are **tests**, not the answer to whether the real GSS model will find 20
eligible items after multi-mapping, nor whether real OpenAI will consistently
choose the intended native categories.

For focused developer iterations:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 -m pytest -q -rs \
  human_study/tests/test_v3_schedule_and_simulation.py \
  human_study/tests/test_v3_multi_observations.py
```

The new test files must pass before the feature can be considered verified;
they have been committed, but tests have not been run in this assistant's
environment against the full repository and native artifact.

## B. Fault injection and persistence

The service uses Firestore CAS plus a GCS outbox:

1. Commit answer + mapping result + state + pending-export object together.
2. Upload immutable object to GCS; acknowledge/reconcile pending export.
3. Only then expose next question; HTTP answers may be ACKed as saved while
   the next LLM question is preparing.
4. Idempotency keys allow a client to retry an identical answer safely.
5. On a provider failure, store bounded error codes and retry generation
   instead of silently displaying raw source wording.

Run `tests/test_persistence.py` and `tests/test_cloud_adapters.py`. Prior
tests inject errors at CAS/GCS boundaries, but they are **not substitutes**
for database concurrency and Cloud Run load tests. Before human deployment,
extend coverage to 2+ concurrent clients sharing a cookie, stale-version
answers, cold restarts during attention, repeated GCS failures, and simulated
429/503/timeout/repeated invalid question wording. Verify each failure can
be recovered without duplicate answers, skipped questions, or missing GCS
objects.

## C. Real native model integration (required before recruitment)

Offline fixture tests use the synthetic `FixtureAdapter`. On a workstation
with the native GSS 2024 artifact installed, run:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 -m pytest -q -rs human_study/tests/test_human_engine.py
```

The five previously skipped native tests must be run where that model is
available. Additional coverage is needed for V3 multi-item adapter semantics:
native category support, complete baseline index, 20-step scored candidate
availability, exclusion of incidentally observed variables, and deterministic
policy replay under the pinned native model version. This can be performed
offline without contacting real participants or paying OpenAI.

## D. Optional live-language-model synthetic probe

Do **not** expose synthetic responses to a real Prolific cohort.
A separate nonproduction study with a new ID can submit a scripted,
investigator-approved set of artificial written responses to the **real**
OpenAI question/answer interpreter and real native adapter. Measure:

- Generation success/invalid-format/semantic-remapping failure rates,
  attempts and timeouts by item and by phase.
- Claimed variables, confidence, literal evidence, native category validity,
  rejected mappings, repeated answers and contradictions.
- Whether generated attention prompts preserve their scoring instruction.
- Whether a simulated 6+20+5 run completes with sufficient eligible items.
- Stability across repeats, paraphrases and varied response lengths,
  including ambiguous answers, refusals, negation and sarcastic wording.

A live-probe runner using OpenAI is **not yet implemented**; do not confuse
`scripts/check_v3.sh` with such a probe. Use a staging service and a
different `study_id`; keep artificial inputs out of paid participant studies.

## E. Cloud Run staging acceptance checklist

Before calling a deployment ready, execute an isolated staging run and
record exact source commit, study config hash, native model version and
pinned OpenAI version. Verify:

- HTTPS, CSRF and signed-cookie semantics; old V1/V2 sessions are not
  silently resumed into V3, and different V3 revisions use distinct IDs.
- Eight-screen short pilot and 31-screen full-length sample complete.
- Attention can appear mid-baseline and mid-intervention, preserves resume
  index, retains no native categories, and logs a pass/fail.
- Every substantive screen is LLM-generated (no raw-text fallback).
- Every accepted human answer contains the original prose and all
  accepted/rejected/conflicting model mapping decisions.
- No double writes after browser refresh, duplicate POST, Cloud Run restart,
  or intermittent GCS connectivity.
- Archive count equals expected count; all presented and answered snapshots
  remain immutable; `final.json` has a reproducible ideology trajectory.
- Service identity cannot delete completed archived objects; observed costs
  and p95 latency remain acceptable; concurrency does not corrupt sessions.

To retrieve latest completed session:

```bash
python3 human_study/scripts/analyze_v3_trajectory.py
```

This investigator command reads private GCS through Application Default
Credentials. It does not contact the user-facing participant service.

## F. Methodology tests beyond software

The LLM's stated assignment confidence is **not calibrated**. Add an
independent blinded annotated corpus of real written answers, including
multi-domain answers, text that appears to contradict itself, silence or
refusal, and distractor topics. Report precision/recall and false-positive
native-state assignments *per variable and category*, inter-annotator
agreement, and effect of misclassification on the ideology index. Do not
promote a successful deterministic synthetic session as human scientific
validation. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
