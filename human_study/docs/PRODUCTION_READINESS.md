# DTAG Human Study V3 — production-readiness and final-study specification

**Status as of 2026-10-25:** The internal software regression suite passed locally
(27 V3/optimizer tests, 36 persistence/API/cloud-adapter tests, frontend
TypeScript and Vite build). A separate real-native GSS 2024 parity audit
matched the DTAG webapp at three tested states (empty, two observed,
four observed coordinates). This is **not** an approval to recruit participants:
real OpenAI-language performance, actual Cloud Run concurrency, experimental
validity, privacy, and compensation remain separate acceptance gates.

This file records the investigator's proposed target configuration and the
work needed to move beyond the short **4 baseline + 3 adaptive + 1 attention**
internal pilot. It does not modify any selection or state-update algorithm.

## 1. Intended study dimensions

| Component | Current short V3 example | Proposed final study | Requirements |
| --- | --- | --- | --- |
| Baseline substantive questions | 4 | **5–6**, preferably **6** initially | Independently review source wording, response support and baseline coverage |
| DTAG adaptive substantive questions | 3 | **20** | Set `intervention_steps: 20`; dynamically select from full eligible native model each step |
| Attention checks | 1, terminal | **5**, interleaved | Configurable `after_substantive` positions, non-LSM, no ideology updates |
| Held-out outcome questions | None in short V3 example | Protocol-dependent; **distinct from the 20 adaptive questions** | Prespecify measurement and retention; do not use held-out outcomes to adaptively condition the state |
| Total respondent screens (excluding consent) | 8 | **30–31 plus any held-out outcomes** | Six baseline + 20 adaptive + five attention = 31 |

For a six-baseline/20-adaptive study, an illustrative schedule for the five
attention checks is `after_substantive: [3, 8, 13, 18, 24]`. This places one
check within baseline and four among adaptive questions. Positions count
**substantive answers already saved**, not screen numbers, and are not a
fixed schedule mandated by the algorithm. Other timings should be prespecified
to balance respondent burden and avoid predictable check placement.

**Crucial:** A proposal for 20 adaptive questions does **not** imply fixing a
bank of 20 (or more) GSS variables. V3-native uses the original DTAG webapp
native-item discovery `optimizer.session_push.askable_items()` and ranking
geometry `optimizer.one_step_geometry.native_one_step()` after each updated
state. There is no YAML whitelist of adaptive question candidates. The native
webapp may return no positive/negative movement in the requested direction;
the final protocol must decide how to count and report this outcome, not
silently substitute a different optimizer.

## 2. Required V3 configuration changes

Use a **new study ID** and a fresh externally reviewed configuration derived
from `config/study.v3.interleaved.example.yaml`. Do not overwrite a frozen
pilot instrument or redeploy across active participants. An *illustrative
fragment* is:

```yaml
study_id: prolific-v3-full-draft
reviewed: false
initial_steps: 6
intervention_steps: 20
question_mode: llm_required
response_mode: free_text_multi
candidate_mode: native_webapp
push_response_mode: draw
max_response_assignments: 50
minimum_mapping_confidence: 0.8
attention_checks:
  - check_id: attention_reading_01
    instruction: "Write a short reply containing the exact word cobalt."
    expected_token: cobalt
    after_substantive: 3
  - check_id: attention_reading_02
    instruction: "Write a short reply containing the exact word violet."
    expected_token: violet
    after_substantive: 8
  - check_id: attention_reading_03
    instruction: "Write a short reply containing the exact word amber."
    expected_token: amber
    after_substantive: 13
  - check_id: attention_reading_04
    instruction: "Write a short reply containing the exact word cedar."
    expected_token: cedar
    after_substantive: 18
  - check_id: attention_reading_05
    instruction: "Write a short reply containing the exact word orbit."
    expected_token: orbit
    after_substantive: 24
```

**This fragment is not a deployable instrument.** The complete YAML also
requires the consent, model/map references, reviewed baseline `items`,
ethics restrictions, versioning, investigator approval, and any distinct
held-out outcome items. It intentionally does not include an `intervention`
item list. Attention instruction words are examples only and should be
reviewed/rotated in a real protocol; the model must generate participant-facing
wording preserving the specified token.

The existing short examples contain only **four** baseline items. Add one or
two *investigator-reviewed* baseline survey questions with real GSS native
labels and valid wording. Do not invent IDs or make the LLM select baseline
variables arbitrarily. Review whether the existing `health` baseline item
should be retained, given the target is opinions/worldviews rather than
a medical phenotype. Changing baseline items alters the scientific experiment
and requires explicit approval, a new config hash, and a new study ID.

`max_response_assignments: 50` follows the webapp's configured
`max_assign`, but the evidence-backed **human** category interpreter remains
a different operation from the simulated respondent's `draw`: do not use
conditional model draws as human observations. Review classifier output limits,
LLM latency and cost when increasing from 5 to 50 allowed mappings.

## 3. Algorithm-fidelity contract (must not drift)

- **Model:** native GSS 2024 LSM, pinned artifact, original DTAG canonical map.
- **Poles:** request webapp-registered `gss_default`. The shared
  `build_polar_geometry()` correctly resolves to the GSS 2024 wave-specific
  pole file; provenance captures both canonical and resolved file hashes.
- **Selection:** original `optimizer.session_push.askable_items` opinion filter
  plus original `optimizer.one_step_geometry.native_one_step`. `draw` ranks
  `expected_delta` rather than the modal-response change. Preserve original
  up/down sign and tie ordering. Recompute after each accepted state update.
- **Written-response variable discovery:** call the shared
  `DTAGSession.map_question` with the webapp `configs/dtag_config.yaml`
  parameters; when no direct mapping succeeds, reuse the original semantic
  prefilter/bridge with `semantic_fallback=update_state`.
- **Human category interpretation:** distinguish variable discovery from native
  *value* assignments. Only validate explicit quoted human evidence, original
  native labels and confidence threshold. This additional human measurement
  layer is **not** equivalent to drawing synthetic responses in the webapp and
  must be benchmarked separately.
- **State update:** apply all accepted human assignments jointly, with
  same-variable revisions, original webapp `state_keep` / LRU eviction
  semantics, immutable original responses, and reproducible ideology index.
  Attention responses never enter the LSM.
- **No fixed adaptive whitelist, no invented semantic shortcuts, no change to
  the webapp optimizer.** Proposed science-policy deviations must be reviewed
  separately and versioned rather than silently added to V3.

Current native GSS audit:
```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 human_study/scripts/audit_webapp_native_parity.py
```

The most recent supplied successful audit tested empty, 2-observation,
and 4-observation states, comparing candidate sets, geometry indices,
expected deltas, poles, and directional choices. It does **not** cover
every possible 20-step trajectory.

## 4. End-to-end automated testing and acceptance

The following passed in the user's local environment:

```bash
bash human_study/scripts/check_v3.sh
```

- 27 V3/scripted/interleaved/native-webapp-parity tests;
- 36 persistence, conflict, cloud-adapter and API regression tests;
- TypeScript check and Vite production build.

The synthetic **6+20+5** test is a state-machine and archive-count test with a
fixture model and scripted LLM. It proves that 31 screens can be sequenced,
answered and archived in the test harness; it does **not** prove 20 directional
questions can always be discovered with the real native GSS model or that
the real LLM accurately interprets diverse human answers.

Before actual recruitment, run and record:

1. **Native trajectory stress:** multiple initial persona/response states;
   dynamic 20-step `draw` selection, candidate counts, exact direction signs,
   and early-no-direction cases. Compare every step with original webapp output
   and compare full index trajectories.
2. **Live LLM synthetic probe:** scripted heterogeneous written answers through
   the **real** direct mapping, semantic fallback and evidence interpreter
   using the pinned model. Cover negation, ambiguity, contradictory opinions,
   unrelated incidental topics, repeated variable updates and missing answers.
   Report mapping precision/recall against blinded human annotations, not just
   a green JSON-schema test. The live OpenAI probe runner is **not yet built**.
3. **Cloud Run staging:** real Firestore CAS/GCS write-once semantics under
   concurrent duplicate submissions, generation timeouts, 429s, restart and
   response replay. Ensure a pending NEXT-question export does not mask an
   archived answer, while an unarchived ANSWER still blocks progression.
4. **Participant browser:** mobile/desktop, keyboard accessibility, long answers,
   refresh/resume, five interleaved checks, deterministic success receipts
   and no native choices exposed. Perform a complete **31-screen** staging run.
5. **Independent archival audit:** `final.json`, consent version, attention
   positions/results, mapping provenance, model hashes, exported original prose,
   native state/index updates and replay reproduce the expected records.
6. **Operational limits:** p50/p95/p99 latency, LLM/API retries, native scoring
   resource use, 31-screen dropout rate, projected cost and concurrency limits.

A passing build is **not** automatically a passing deployed production study.

## 5. Scientific experiment and participant protocol

Before deploying to Prolific, investigator approval is required for:

- Clear operational definitions of baseline worldview, ideology trajectory,
  phenotype refinement, belief change and intended directional push.
- Randomization to intervention directions and any controls, preregistered
  hypotheses/analysis, and whether a post-interaction measurement is actually
  independent of the adaptive LSM conditioning state.
- Held-out outcome item strategy for evaluating genuine response change versus
  simply revealing previously unobserved worldview coordinates. Set outcomes
  aside *before* adaptation; never allow incidental answer mapping to consume
  held-out outcome coordinates during the experiment.
- Baseline wording/categorization quality, age eligibility, informed consent,
  attention-check scoring/review, meaningful compensation, participant rights,
  and privacy/retention/deletion requirements.
- **Context-free wording gate for every participant-facing question.** The GSS
  2024 map contains conditional/grid fragments such as `colmslm` (a
  referenced person is absent when asked independently), incomplete spending
  and abortion stems, and an unfinished `eqwlth` question. Source-grounded
  generation contracts now protect 102 map items. The whole-map audit
  (`scripts/audit_gss_wording_map.py --check`) covers 813 variables and
  reports 13 outstanding context-suspect items requiring classification;
  see [wording-audit findings](GSS_2024_WORDING_AUDIT.md). Before recruitment,
  run `--native-candidates --check` against the actual GSS native model and
  review live LLM-generated questions from multiple adaptive trajectories.
  The unresolved experimental `racdif1x-5x` labels are explicitly excluded
  from the current Prolific candidate universe.
- Independent annotation of a representative sample of written-answer to
  native-category mappings; measure false positive conditioning errors and
  their effect on directional index movement.
- Five visible, verbatim instructed-response checks (not factual trivia), using
  the validated full-study schedule at substantive positions 3/8/13/18/24.
  The conservative `eligible_for_rejection` flag is based on ≥3 valid IMC
  failures, or ≥2 failures plus independent, sustained, objectively obvious
  keyboard-mash gibberish. The 0–100 quality-risk score never suffices.
  Eligibility is **not** an executed rejection or payment determination.
  Preserve exact failed-check text, answers, objective evidence and rule
  version in private archives; verify each case before any Prolific action.
  See [Prolific quality policy](PROLIFIC_QUALITY_POLICY.md).
- A pilot audit of question accessibility and clarity, completion times and
  unexpected IMC failures. Do not deploy a paid study until the investigator
  approves the frozen IMC instrument, eligibility rules and compensation paths.

Prolific linkage (PID/STUDY_ID/SESSION_ID), one session per PID,
completion/eligibility records, and three completion paths are implemented
(see the README "Prolific deployment" section,
`config/study.prolific.example.yaml` and
[the preregistration-ready quality protocol](PROLIFIC_QUALITY_POLICY.md)).
The participant-facing review code only *flags* a potentially rejection-
eligible submission. Paying, approving or rejecting submissions remains an
explicit investigator action in Prolific; a Prolific-valid reason and evidence
must be documented.

## 6. Operational packaging and release process

- Source-controlled `config/study.v3*.example.yaml` files are drafts with
  `reviewed: false`. Actual reviewed configs belong in a secure, external path.
- Use `deploy/deploy.sh` dry-run first; `--execute` performs deployment.
  Isolate the full-study ID/service from the existing short pilots and from
  their archived respondent data.
- Freeze source SHA, model artifact SHA, map SHA, effective pole SHA, question
  prompt version, LLM model choice, baseline bank, direction policy and
  attention schedule before recruitment.
- The frontend Docker stage uses Node 22.21.1. Local Node 20.17.0 produced a
  Vite compatibility warning but still completed its build; move local
  development to Node 22.12+ and rerun the build.
- Do not label the 31-screen synthetic test as a production qualification.
  Complete all above acceptance gates and record investigator sign-off.

## 7. Navigation

- [Architecture and native state invariants](ARCHITECTURE.md)
- [Automated testing, injections and deployment checks](TESTING.md)
- [Top-level study README](../README.md)
- [V3 implementation details](../V3_IMPLEMENTATION.md)

Historical M01/M02 files are retained separately; they describe earlier
click-category pilot milestones, not the current native-webapp V3 protocol.
