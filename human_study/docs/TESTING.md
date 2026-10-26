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

These are **tests**, not evidence that the real GSS optimizer always produces
a positive/negative directional choice on a 20-step trajectory, nor that real
OpenAI consistently maps written responses into the intended native categories.
The adaptive candidate universe is dynamic and unrestricted by a YAML
intervention-variable bank.

For focused developer iterations:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 -m pytest -q -rs \
  human_study/tests/test_v3_schedule_and_simulation.py \
  human_study/tests/test_v3_multi_observations.py
```

**Verified local result (2026-10-25):** the user ran the complete
`scripts/check_v3.sh` suite successfully: **27 V3/parity tests, 36
persistence/API/cloud-adapter tests, and a passing frontend build**.
The test fixture is still not evidence of live OpenAI semantic accuracy.
The user also ran the full-native geometry parity audit successfully.

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

The user's installed GSS 2024 artifact has already passed the separate
numerical parity audit:
```bash
python3 human_study/scripts/audit_webapp_native_parity.py
```
It verified the actual requested/corrected 2024 pole geometry, 228 dynamic
candidate variables in the empty state, and matching native ideology and
up/down `draw` selections for empty, 2-coordinate and 4-coordinate states.
Run the wider native integration suite, and extend the audit to multiple
20-step trajectories before recruitment. The historical native tests may
require installed bindings and downloaded artifacts.

### GSS 2024 standalone-wording source audit

The 2024 map includes dependent question fragments (e.g. `colmslm` without
the referenced Muslim clergyman). Before paid deployment, use the offline map
audit to check contractual sources and unresolved wording-experiment exclusions:

```bash
python3 human_study/scripts/audit_gss_wording_map.py --check
```

For the actual *empty-state askable opinion pool*, with the real native model
installed, additionally run:

```bash
python3 human_study/scripts/audit_gss_wording_map.py --native-candidates --check
```

Both audits are read-only. The first is in CI and the offline V3 verification
script. The second uses the native model and is not run by CI because the model
artifacts are not guaranteed present; it should be run before recruiting.
Neither replaces investigator review of representative generated questions,
especially after multi-item conditional state updates. See
[GSS 2024 wording-audit report](GSS_2024_WORDING_AUDIT.md).

## D. Optional live-language-model synthetic probe

Do **not** expose synthetic responses to a real Prolific cohort.
A separate nonproduction study with a new ID can submit a scripted,
investigator-approved set of artificial written responses to the **real**
OpenAI question/answer interpreter and real native adapter. Measure:

- Generation success/invalid-format/semantic-remapping failure rates,
  attempts and timeouts by item and by phase.
- Claimed variables, confidence, literal evidence, native category validity,
  rejected mappings, repeated answers and contradictions.
- For the **Prolific** instrument, verify that all five attention prompts are
  verbatim, conspicuous IMCs (cobalt/violet/amber/marble/cedar) and that the
  exact response-word instruction is shown in the current question. Generic V3
  experimental configs may still test LLM-written attention prompts.
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
  index, retains no native categories, and logs a pass/fail. For the Prolific
  instrument, validate the 3/8/13/18/24 IMC schedule and the exact five tokens.
- Test the three Prolific completion paths against the live study setup; a
  flagged `eligible_for_rejection` case routes to investigator review rather
  than executing a rejection or deducting pay. Verify 0/1/2/3 IMC failures,
  two failures plus many meaningful duplicates (not eligible), and two
  failures plus prolonged clear keyboard-mash gibberish (eligible pending
  evidence review). Confirm archived `rejection_eligibility` in `reward.json`
  and `final.json`, and CSV export. See
  [Prolific quality policy](PROLIFIC_QUALITY_POLICY.md).
- Every substantive screen must be a *complete, defensibly grounded*
  respondent-facing question. The primary path generates and validates LLM
  wording; if that fails twice, an existing audited standalone GSS source
  can be displayed with `provider=source-validated`, an explicit
  `validation_method` and recorded failed LLM attempts. For uncontracted
  items, a conservative structural check is required before an original
  map prompt can be displayed; abbreviated/dependent map fragments must
  continue to fail closed. This is an explicit source-grounded exception
  to the original LLM-only presentation rule and must be reflected in
  participant consent before paid recruitment.
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
