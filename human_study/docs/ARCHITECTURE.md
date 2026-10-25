# DTAG human study — architecture and invariants

Status: research-engineering pilot, not validated for Prolific enrollment. The
`human_study` app is a distinct participant-facing implementation of the
DTAG/LSM framework; it is not a generic chatbot and has no public investigator
API. See [TESTING.md](TESTING.md), [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md)
and the root [README](../README.md).

## System overview

```text
 Participant React UI (frontend/src/main.tsx)
     | same-origin JSON, signed anonymous browser cookie
 FastAPI (backend/human_study/app.py)
     | session + answer coordination
 StudyService (service.py)
     |                           \
 FirestoreRepository             GCSArchive  [create-only immutable objects]
  CAS/revision                    manifest, question-presented, answer, final.json
     |
 QuestionLLM (questions.py) -- OpenAI (no fallback in V2/V3)
     |
 MultiObservation validator (multi_observations.py)
     | strict native categories; explicit evidence; contradictions audited; native-webapp mode updates state
 NativeAdapter (adapter.py) -> pinned GSS 2024 LSM
     |
 DTAG policy (policy.py) -> next eligible unasked variable
```

All science-critical model decisions use real native LSM operations on the
deployed instance. The *offline synthetic test adapter* is ONLY a test harness
and makes no claims about GSS distributions, actual humans or persuasion.

## Study versions, naming and backward compatibility

- V1: click-category / original multi-phase pilot; records retained.
- V2: LLM-only questions, one written answer -> at most one native observation.
- V3: LLM-only questions, one written answer -> zero or more **validated**
  native assignments; optionally scripted attention checks. The aligned V3
  example uses `candidate_mode: native_webapp` and `push_response_mode: draw`.
- The short V3 example is `config/study.v3.example.yaml` (4 initial + 3
  adaptive + 1 terminal check). The *new* isolated interleaved example is
  `config/study.v3.interleaved.example.yaml` (4+3, checks after substantive
  answers 2 and 5). It has a separate study ID.
- Changing an instrument or the code changes immutable provenance/config
  hashes. **Do not redeploy over an active participant cohort.** Version
  a study ID and preferably deploy another Cloud Run service.

## Participant and session lifecycle

`consent -> baseline -> intervention -> [outcome if configured] ->
ready_to_complete -> complete`. V3 *temporarily* interrupts baseline or
intervention with `attention` without modifying the main experiment state.

A session persists `phase`, `phase_index`, `next_step`, and a native
`state`. V3 attention scheduling additionally persists:

- `attention_cursor`: next configured check to present;
- `attention_completed`: number of checks already answered;
- `resume_phase`, `resume_phase_index`: the saved scientific phase/position.

The substantive count is `next_step - attention_completed`. An attention
check with `after_substantive: N` appears immediately after the Nth
**substantive answer** is committed. `0` means before the first baseline
item, `null` (or omitted) means after the last adaptive answer. Checks must
be sorted by placement; adjacent checks at the same boundary run in list
order. The attention response contains no survey native category, does not
increment adaptive-policy steps and never updates ideology.

The state machine writes all phase transitions and the completed question
atomically in a Firestore compare-and-swap transaction. It also emits an
outbox record for immutable GCS export. The browser can receive a committed
answer acknowledgement with a pending next question; it polls `current`
rather than resubmitting the answer. API status 503 is used for transient
generation or GCS synchronization delays; inconsistent records remain errors.

## Scientific invariants

1. Baseline ideology is computed *once*, after all baseline answers, from
   the union of accepted native assignments. Four questions can yield more
   than four native observations.
2. A V3 classifier proposes at most `max_response_assignments` items,
   providing native variable, native category, confidence and a literal
   evidence span from the human's prose.
3. Server validation rejects variables outside the shared DTAG mapping output, ethically excluded, held-out,
   unsupported, low-confidence or unquoted assignments. A text span check
   is an audit safeguard, **not** an independent semantic correctness proof.
4. Identical native repeats are *confirmations*. Contradictory native
   human statements remain recorded as *conflicts*. In `native_webapp`
   mode a later valid answer updates the coordinate (the original webapp's
   state-update semantics), while historical instrument mode preserves
   the old value. Every prior statement remains auditable.
5. In `native_webapp` mode, adaptive candidates come directly from
   `optimizer.session_push.askable_items` and are scored with
   `optimizer.one_step_geometry.native_one_step` at each new native
   respondent state. There is no instrument/YAML intervention whitelist.
   Native `draw` uses the expected change objective; the webapp can stop
   a right/left push when no correctly directed item remains.
   Explicit study exclusions and reserved outcome coordinates remain separate
   from algorithmic candidate selection.
6. After an adaptive response, all accepted assignments are applied
   atomically before a *single* native index computation.
7. `observed_conditional_index_delta` refers to the **joint observed**
   multi-variable update; `predicted_model_delta` is the optimizer's
   **single-target expected** movement. They are not the same estimand.
8. Only explicit human statements create observed coordinates. LSM
   conditional distributions and LLM speculation are never passed off as
   human responses. This alone does not prove causal persuasion.
9. Attention checks have no model-coordinate updates; `attention_passed`
   is a quality annotation only. No automated payment/rejection decisions.
10. The archived `final.json` contains the full config, presented wording,
    raw answers, interpretation provenance, mapping decisions, attention
    results, policy trace, and stored native index values.

## Deployment and security boundaries

Source path `deploy/deploy.sh` is DRY-RUN unless invoked with `--execute`.
It builds only from clean committed Git history and injects an externally
reviewed YAML. Staging/production require a reviewed instrument, real
native model, OpenAI, durable Firestore and GCS, stable Secret Manager keys,
and an exact HTTPS origin. The app mounts only participant endpoints;
investigator extraction is a private CLI and GCS credential workflow.

Cookies are HTTP-only/SameSite, anonymous session IDs and user-provided
answers are not exposed as analytics in public API responses. GCS objects
are create-only, and participant text must never be committed to Git.
See the historical M01/M02 reports in [history/](history/) for previous
deployment threat models.

## Operations/diagnostics

From repository root, after activating the Python environment:

```bash
bash human_study/scripts/check_v3.sh
python3 human_study/scripts/inspect_pending_v3.py
python3 human_study/scripts/analyze_v3_trajectory.py
```

The first command is entirely offline; the latter two use investigator
Google Cloud credentials. See [TESTING.md](TESTING.md) for scope and failure
injection and [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for remaining
deployment, scientific and human-subject gaps.
