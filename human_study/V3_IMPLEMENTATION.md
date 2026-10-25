# Human study V3: multi-item free-text conditioning

Implementation branch: `experiment/prolific-human-study`. Status:
**committed for internal testing, not yet deployed/verified live.**
The V2 `pilot-v2` and V1 `pilot-001` study IDs and completed GCS archives are
unchanged; the native-webapp-aligned configuration uses distinct `pilot-v3-native` IDs.

## Experiment shape and constraints

- `initial_steps: 4`: four initial, LLM-generated GSS questions.
- `intervention_steps: 3`: three DTAG-selected, LLM-generated questions.
- `attention_checks`: one separately generated instructed-response check
  at the end of the short sequence. It is **not** a model coordinate,
  not an intervention, and does not move the ideology index.
- The participant sees **eight screens** after consent: 4 initial + 3
  adaptive + 1 attention. Baseline and trajectory have **seven** substantive
  answers and one check.
- `question_mode: llm_required`, `response_mode: free_text_multi`.
  There are no clickable native categories and **no question-text fallback**.
  Provider/semantic validation failure leaves the question pending.
- `max_response_assignments: 50` (the webapp's configured `max_assign`) and
  `minimum_mapping_confidence: 0.8` are tunable. Assignment count can be
  zero for an explicitly nonresponsive/declining written reply.

## Multiple survey observations per written response

V3 presents the exact generated question and the participant's own words
to an LLM. Unlike V2, the model can propose **up to K independent GSS
variable/value assignments**, not just the selected question's variable.

The current V3-native example has **no adaptive intervention variable bank**.
At each adaptive step, the native optimizer discovers every askable,
unanswered opinion variable from the installed GSS model using the exact
webapp function `optimizer.session_push.askable_items`, and obtains one-step
geometry from `optimizer.one_step_geometry.native_one_step`. With
`push_response_mode: draw`, right/left rank by the original webapp's
`expected_delta`, never the modal-response displacement.

For each recorded written answer, `DTAGSession.map_question` is called
on the generated question and participant's own words using the same
`configs/dtag_config.yaml` k/prefilter settings as the webapp. If it does
not find relevant variables, the native webapp semantic fallback invokes the
same embedding prefilter and semantic bridge under `update_state`.
The returned native variable IDs are passed unchanged to an evidence-checked
human **category** interpreter. Native conditional `draw` values are
**not** substituted for what participants wrote, since the original webapp
simulates answers rather than observing real humans. Experimental ethical
exclusions and separately reserved outcomes still apply.

The classification prompt prohibits inferring answers from correlations,
social stereotypes or population-level conditional predictions.
Every candidate mapping must include the exact source quote from the
participant's response, category, and confidence. The server separately checks:

1. The variable was selected by the original DTAG mapper and is not ethically excluded or reserved for outcome measurement.
2. The category is in the full native LSM response support for that variable.
3. Confidence meets the configured cutoff (currently 0.80).
4. The evidence is a verbatim span of the actual written response.
5. The same variable is not assigned twice in one reply.
6. Consistent repeats become `confirmations`; incompatible repeats
   are retained in `conflicts` with prior and proposed values. In native
   webapp mode the latest independently validated observation **revises**
   the state, as in DTAGSession._answer_with_variables; legacy instrument
   mode retains its original no-overwrite behavior. Invalid mappings
   become `rejected`.

Only validated, **new** observations are added to the state. The immutable
response record stores `accepted_assignments` and the interpretation's
`proposed`, `accepted`, `confirmations`, `conflicts`, and `rejected`.
All proposed mapping provenance is preserved for research audit.

If no valid or confirmatory/conflicting interpretation remains, the UI
requests a clarification without moving to the next question.
Explicit declining/missing replies may advance without a new coordinate;
no answer is manufactured from the native model.

The four baseline questions can therefore yield *more than four*
observed phenotype coordinates. Adaptive selection is recomputed after each state update through the
original webapp's native askability and geometry functions. The native-webapp
mode excludes assigned coordinates, pole items (as the webapp does by default),
and explicit study reservations; it does not use a YAML whitelist. The webapp's
right/left direction may legitimately stop early when no positive/negative
candidate remains. The resulting stop reason is persisted.

## Geometry and replay

At the end of the initial phase, V3 builds one LSM state from the union
of all four replies' accepted assignments and computes `baseline_index`.

For each adaptive question, all newly accepted assignments are applied
in a single state update, followed by **one** native ideology evaluation.
`index_before`, `index_after` and
`observed_conditional_index_delta` represent the joint change from
**all** accepted assignments. The optimizer's
`predicted_model_delta` still represents only the one selected **target
variable** and must not be misrepresented as a prediction for the combined
set. Both scopes are recorded explicitly.

The pure `multi_observations.replay()` recalculates baseline, checks
adaptive-policy selection from the recorded RNG state, reapplies the exact
archived accepted assignments, and verifies every ideology index without
asking the LLM to interpret the response again.

**This is movement of the learned LSM's conditioned ideological index,
not evidence of a change in the human participant's beliefs.**

## Attention check

The sample contains an investigator-specified one-word reading-instruction
check; its respondent-facing wording is generated by the LLM, and the
designated token must remain intact (otherwise generation is rejected).
Its evaluation is a deterministic word-boundary comparison, archived as
`attention_passed` and `response_interpretation.status=attention_check`.
No attention response can create a native LSM observation. A failed check
is **flagged**, not used automatically to disqualify or invalidate a study
session. This one-token check is a simple internal-pilot device, not yet
a validated anti-bot or study-quality protocol.

## Files

- `human_study/config/study.v3.example.yaml` — seven model questions, one
  optional external attention check, `reviewed: false`.
- `human_study/backend/human_study/questions.py` — multi-assignment LLM
  schema; LLM-generated attention prompt with exact token requirement.
- `human_study/backend/human_study/multi_observations.py` — trusted
  candidate list, validation, conflict resolution, atomic conditioning,
  deterministic archive replay.
- `human_study/backend/human_study/service.py` — state/storage/selection
  integration with existing Firestore and GCS outbox protocol.
- `human_study/tests/test_v3_multi_observations.py` — synthetic end-to-end
  and unit regression tests.
- `human_study/scripts/analyze_v3_trajectory.py` — investigator-only
  `final.json` analysis for ideology and all accepted assignments.

## Running the checks

From repo root:

```bash
git pull --ff-only
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 -m pytest -q \
  human_study/tests/test_v3_multi_observations.py \
  human_study/tests/test_v2_written_responses.py \
  human_study/tests/test_human_engine.py \
  human_study/tests/test_human_api.py \
  human_study/tests/test_persistence.py \
  human_study/tests/test_cloud_adapters.py
(cd human_study/frontend && npm ci && npm run build)
```

For a Cloud Run **internal test only**, create a separate, investigator-reviewed
copy of `study.v3.example.yaml`, setting `reviewed: true` only after reviewing
the baseline questions, reserved outcomes and attention instructions. Keep the distinct `pilot-v3-native` study ID.
Set `DTAG_REVIEWED_CONFIG` to this copy and the prior GCP environment variables;
use `bash human_study/deploy/deploy.sh` for a dry run. After reviewing
deployment and source of truth, use `--execute`. The existing service is
replaced when deployed under the same `GCP_SERVICE`; old sessions may no longer
resume, but their immutable archives are not overwritten. Prefer a separate
V3 test Cloud Run service.

For completed V3 sessions:

```bash
python3 human_study/scripts/analyze_v3_trajectory.py
```

It discovers the latest `pilot-v3` `final.json` and prints the four-point
LSM baseline+adaptive trajectory and all native assignments, conflicts being
available in the raw `final.json`. It writes local CSV/PNG under
`/tmp/dtag-v3-analysis`.

### Research limitations

LLM-assessed mapping confidence has **not** been statistically calibrated.
A verbatim evidence span is a necessary audit safeguard but not a sufficient
guarantee of correct category semantics. Further blinded human annotation
and comparison with the 2024 official GSS question forms remain necessary,
particularly for partial/questionnaire-form-specific source stems.
Do not recruit Prolific respondents with this unreviewed pilot YAML.
