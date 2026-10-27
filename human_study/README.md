# DTAG human-response study

Current work: **V3 native-webapp-aligned written-response study**, developed on
`experiment/prolific-human-study`. Earlier M01/M02 click-response work remains
in this folder and is retained for historical reproducibility. The standalone
participant webapp does not replace the DTAG simulator/research webapp.

**Latest verified local status (2026-10-25):** 27 V3/interleaving/parity tests,
36 persistence/API/cloud-regression tests, and TypeScript/Vite build passed.
A separate real native GSS 2024 audit matched the original DTAG webapp's
candidate discovery, pole-resolved ideology, and `draw`-based up/down picks
at empty, 2-coordinate and 4-coordinate states. This is **internal research
software**, not yet a validated Prolific or production protocol.

## Start here

| Document | Purpose |
| --- | --- |
| [Architecture and scientific invariants](docs/ARCHITECTURE.md) | Native LSM selection, multi-variable human observations, provenance, Firestore/GCS, and attention scheduling |
| [Automated testing and staging validation](docs/TESTING.md) | One-command regression, native-model audit, simulated and live LLM test boundaries |
| [Final-study plan and production readiness](docs/PRODUCTION_READINESS.md) | Required changes for ~6 baseline + 20 adaptive + 5 attention questions, science review, and remaining acceptance gates |
| [V3 implementation details](V3_IMPLEMENTATION.md) | Schema, question generation, evidence-backed mapping and historical development notes |

### What V3 actually does

1. Present reviewed baseline questions; accept freely written human answers.
2. Map each recorded response to **multiple native GSS variables** through
   shared `DTAGSession.map_question()` and original `update_state` semantic
   fallback. A separate evidence-checked interpreter extracts native response
   values from the actual human prose. Synthetic native `draw` responses
   are **not** used as participant observations.
3. Build the baseline native LSM state from accepted mappings. Adaptively
   discover and score questions using **the original webapp functions**:
   `optimizer.session_push.askable_items()` and
   `optimizer.one_step_geometry.native_one_step()`.
   The directional objective uses `push_response_mode: draw` (expected
   ideological displacement). No YAML intervention-variable whitelist exists
   in the native V3 examples.
4. After each substantive response, update all accepted native assignments
   jointly, archive the complete interpretation/provenance, recompute ideology,
   and select the next question. Native-mode revisions and
   `state_keep` eviction preserve webapp state semantics.
5. Interleave investigator-authored attention check *specifications*
   (LLM-rendered, non-LSM) using `after_substantive` positions. Their pass
   or fail never updates the native state.

The shipped **short internal examples** are
[4 baseline + 3 adaptive + 1 final attention](config/study.v3.example.yaml)
and [4 baseline + 3 adaptive + 2 interleaved attention](config/study.v3.interleaved.example.yaml).
Both are unreviewed examples and must **not** be mistaken for the proposed
[full 6+20+5 protocol](docs/PRODUCTION_READINESS.md). The full-study adaptive
questions remain dynamically selected across the installed native model.

### Session choice on every browser load

On opening or refreshing `/study`, the participant sees **Resume saved session**
or **Start new session**. Resume uses the existing signed-cookie session and
keeps its saved answers; with no prior session, Resume begins a new one.
Start new deliberately creates a different session ID, returns to consent and
question 1, and replaces the browser cookie. Previous sessions and GCS/Firestore
records are preserved, not deleted. The UI and endpoint work the **same in
local, staging, and production**. A Prolific link retains its participant
identifiers in the new attempt. Because a deliberate restart can produce
multiple scientific sessions linked to one Prolific PID, research exports
should distinguish attempts and deduplicate participants before analysis;
a restart does not create additional payable Prolific submissions.

A new session can also recover from an obsolete cookie after a code/instrument
update, without wiping browser data or the study bucket.

### Adaptive repetition and question-generation reliability (2026-10-26)

The human participant selector now permanently excludes **all previously asked
native target IDs**, not only the subset still in the bounded LSM state.
Source-documented alternative questionnaire forms and repeated batteries
(e.g. hiring/employment, race identification, racial inequality causes,
citizenship, and GSS historical wording variants) are grouped **within each
session**, so the participant is not asked a near-equivalent question several
times. This does not alter native item IDs, the opinion-item universe, or the
LSM's one-step scoring; different sessions can select different forms.
An additional server-side check prevents *identical displayed wording* even
when the LLM chooses the same phrasing for different source IDs.

The 2024 NORC GSS questionnaire/codebook was consulted to restore **all 16
race-ranking category labels**, complete home-sale discrimination alternatives,
hiring and promotional-preference scenarios, citizenship wording, and the
government/public-area surveillance question. Context is enforced through
source-grounded LLM contracts, with a complete source fallback when needed.

Transient `preparing_question` HTTP responses now trigger automatic browser
polling **without showing a generation error or requiring manual clicking**.
If an adaptive item's source cannot be validated after the bounded LLM
rewrites, the server logs and archives that candidate's failed generation,
selects the next eligible candidate at the same study step, and leaves the
LSM state and submitted answers unchanged. Failures on fixed baseline items
still retry without substituting a different research measure. When replaying
an adaptive session, the immutable generation-skip IDs are included in the
recorded selection so the trajectory is scientifically reproducible.
Unrecoverable external outages can still interrupt the study; none of these
changes constitutes a guarantee of 100% API availability.

To inspect a previous completed `final.json` (including the precise failure
class and validation codes persisted when question generation was retried):

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 human_study/scripts/audit_completed_session.py /path/to/final.json
```

### Paid Prolific study (October 2026)

The paid 20-person first wave has a committed production instrument at
[`config/study.prolific.production.yaml`](config/study.prolific.production.yaml).
It is **not** the `study.prolific.gcptest.yaml` test instrument. Its
`study_id` (`prolific-v3-human-opinions-2026-10`) separates live recruitment
sessions and archived answers from all test sessions. The consent text states
an **estimated 20 minutes** and describes the AI-generated questions and AI
interpretation of free-text responses; the advertised Prolific reward is **USD 8**.

Configured completion paths in the Prolific study (verify the Prolific-side
processing action before publishing):

| Outcome | Completion code | Prolific-side action |
| --- | --- | --- |
| Completed normally | `CTNOTZ30` | Manually review |
| No consent | `CKZYKTSS` | Request a return |
| Meets conservative failed-attention review criteria | `C1J2754F` | Manual review; **no automatic rejection** |

For this production configuration, `prolific.required: true`; a participant
must arrive with Prolific identifiers. Configure **URL parameters** in Prolific
and set the study link to:

```text
https://dtag-human-pilot-gp7m2nymma-ue.a.run.app/study?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
```

A plain service URL without a `PROLIFIC_PID` no longer starts a participant
session when the production instrument is active. Preview using Prolific's
participant flow; do not test with an invented paid participant ID. The
`/study` and `/` paths serve the same participant interface.

Deploy the committed production instrument using the **existing, verified**
Google Cloud bucket/database and runtime secrets. `deploy.sh` defaults to
staging, so explicitly set `DTAG_DEPLOY_ENV=production` for paid recruitment:

```bash
export GCP_PROJECT=pkcsaas-01
export GCP_REGION=us-east1
export GCP_SERVICE=dtag-human-pilot
export DTAG_REVIEWED_CONFIG=human_study/config/study.prolific.production.yaml
export DTAG_DEPLOY_ENV=production
export DTAG_PUBLIC_ORIGIN="$(gcloud run services describe "$GCP_SERVICE" --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')"
# The script reuses DTAG_GCS_BUCKET from the currently deployed Cloud Run service.
# DTAG_FIRESTORE_DATABASE defaults to (default); retain the existing override if used.
# Check the script's dry-run output before allowing any live participants.
bash human_study/deploy/deploy.sh
# After review, run: bash human_study/deploy/deploy.sh --execute
```

The script builds and deploys a new Cloud Run revision with 2 vCPUs/4 GiB
per instance, concurrency 2, min instances 3 and max instances 6. A deployment
changes the active instrument for this shared service URL; never redeploy
while participants are in progress. Before recruitment, verify the production
consent text, code return paths, ID linkage, model readiness, native/LLM
performance, data archiving, and ten-participant concurrency. This repository
change does **not** itself deploy the paid study or authorize recruitment.

### Prolific deployment ([config/study.prolific.example.yaml](config/study.prolific.example.yaml))

The Prolific configuration is **6 baseline + 20 adaptive + 5 interleaved
attention checks** (31 screens), using the same native-webapp selection as above.

- **Baseline ideology.** No persona: six GSS 2024 ideology-pole items
  (`gunlaw`, `grass`, `abany`, `natfare`, `natenvir`, `natarms`) estimate the
  starting index. Against the real native model, all-R answers give index
  +0.23, all-L −0.25, empty state −0.04. The webapp never offers pole items as
  push candidates, so adaptive questions do not re-ask them.
- **Direction.** After the baseline, each participant is uniformly randomized
  to `right` / `left` / `neutral` / `random` (persisted with its RNG state and
  archived as `events/assignment.json`). Right/left/neutral follow the webapp
  and `dtag_persona_push_study.py` definitions (neutral = smallest |expected Δ|).
- **Attention checks.** Five fixed, visible, Prolific-style instructed-response
  checks at substantive positions 3/8/13/18/24 (words: cobalt, violet, amber,
  marble, cedar). All use `kind: instructed_token` and `render: verbatim`.
  The participant sees the explicit instruction alongside the answer box; no
  prior knowledge, memory, timing constraint or LLM rewrite is involved.
  They never touch the LSM state. See
  [Prolific quality/rejection policy](docs/PROLIFIC_QUALITY_POLICY.md).
- **Standalone question validation (GSS 2024).** An audited set of source-
  grounded wording contracts reconstructs missing subjects and question
  stems for `colmslm` and related civil-liberties, abortion, suicide, spending,
  institutional-confidence, policing, gender-role, and inequality item families. LLM-
  generated text must retain the relevant subject and meaning. If both
  LLM rewriting attempts fail, the service now presents the **complete,
  source-validated GSS question** (with explicit archived provenance)
  instead of entering an indefinite retry loop. Uncontracted canonical
  questions are used only if they pass conservative standalone-text checks;
  clearly incomplete fragments are still rejected. This recovers from LLM
  outages and overly restrictive semantic rewrites without presenting an
  orphaned “this person” question. New regression tests exercise the actual
  StudyService presentation/retry path. The recovered text is **not** described
  as an LLM-generated question.
  All five `racdif*x` wording-experiment variants are retained in the
  Prolific candidate pool, with their complete historical-comparison
  introduction and specific causal explanations reconstructed from NORC's
  2024 ballot. No item is removed for incomplete source wording.
  The whole-map wording scanner
  examined **813 native semantic-map rows**, flagged **99** potentially
  context-dependent labels, added **133** source contracts, and identified
  **12** remaining flagged,
  uncontracted entries, mostly conditional/demographic/social questions
  requiring classification. This is not exhaustive scientific certification
  of all dynamically askable questions; run the native-candidate and live-
  LLM audit before recruitment. See
  [GSS question wording audit](docs/GSS_2024_WORDING_AUDIT.md).
- **Answer-quality flags** (stored for each response): `fast` (server-measured
  elapsed time under `quality.fast_seconds`), `short` (fewer than
  `quality.short_words` words), and `duplicate_of` (normalized text at least
  `quality.duplicate_similarity` similar to an earlier substantive answer).
  The V3 mapper may request clarification when it cannot interpret the text.
- **Automatic scientific quality review** (`pilot-review-priority-v1`, computed
  on completion and archived in `reward.quality.review`): a 0–100 **review
  priority score**, not an authenticity probability, from 65×duplicate-answer
  fraction + 25×short-answer fraction + 10×fast-answer fraction. Fractions
  use answered substantive questions only (baseline, intervention, outcome).
  `score >= 35` suggests investigator review; `score >= 60` is high priority.
  Valid instructional-response failures also raise review priority. These
  thresholds are **unvalidated pilot heuristics**; backend latency is included
  in the fast metric, and legitimate short/repeated opinions are possible.
  Crucially, the quality score **never changes the Prolific completion code,
  payout or rejection decision**. Participant-level scores, priority, and signal
  labels are also available in the investigator-only `participants.csv` export.
  The system does not currently retain rejected pre-submission mapper attempts,
  nor does it reliably detect all types of nonsensical or AI-generated text.
- **Prolific linkage.** Set the Prolific study URL to
  `https://<service>/study?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}`.
  Outside local mode a PID is required. Each PID gets one session
  (HMAC of study ID + PID, keyed by `DTAG_COOKIE_SECRET`), so a participant who
  loses cookies resumes rather than restarts. Raw Prolific identifiers are
  written to the immutable GCS research archive **only after consent**.
  Declined sessions discard the PID from their operational session record.
- **Conservative rejection eligibility (not auto-rejection).** Automatic
  `eligible_for_rejection` is **true only for ≥3 failed valid IMCs**, or
  ≥2 failed valid IMCs plus independently observed, repeated, obvious
  keyboard-mash gibberish across most questions. Short answers, semantic
  agreement, repeated meaningful opinions, speed, and the quality score
  **cannot** independently establish eligibility. Exactly two IMC failures
  with a high score yield a separate `two_failures_need_independent_evidence`
  flag, not rejection eligibility. Versioned evidence and failed check IDs
  are archived in `reward.rejection_eligibility` and exported to
  `participants.csv`. An investigator must verify evidence before any
  Prolific action. See [the complete criteria](docs/PROLIFIC_QUALITY_POLICY.md).
- **Three Prolific completion paths.** `completion_code` for ordinary
  completed submissions; `review_code` for *rejection-eligible* cases routed
  to a Prolific **Failed attention checks** path for manual consideration;
  `no_consent_code` to request a return without a study reward. Codes are
  fixed per study, not unique per participant. No code change itself executes
  a rejection or modifies compensation. Stage/production and `deploy.sh`
  reject `CHANGEME` placeholders.
- **Payment restriction.** A review code does **not** change payment on its
  own. Prolific does not permit performance-based partial-pay deductions.
  Manual review is required before any permitted action; genuine completed
  submissions should generally receive the full advertised payment. Technical
  interruption/partial participation is handled under Prolific's documented
  return and partial-payment process rather than this quality flag.
- **Internal GCP testing.** `config/study.prolific.gcptest.yaml` contains
  separate opaque test codes and a versioned test study ID. Those codes are
  **not** usable as Prolific completion paths unless created/configured there.
  Never recruit with the GCP testing configuration.

GCS objects per completed participant (bucket `DTAG_GCS_BUCKET`):

| Object | Content |
| --- | --- |
| `studies/<study>/sessions/<sid>/events/enrollment.json` | Prolific PID, STUDY_ID, SESSION_ID |
| `…/sessions/<sid>/{baseline,questions,attention}/<qid>.json` | every presented question and answer, with attention result and `response_quality` |
| `…/sessions/<sid>/events/assignment.json` | randomized direction, RNG state, baseline index |
| `…/sessions/<sid>/reward.json` and `studies/<study>/rewards/<PID>.json` | completion code issued, code category, reward, attention and quality summary |
| `…/sessions/<sid>/final.json` | everything above plus the full question list and study configuration |

`python -m human_study.export` adds PID, completion code, category, attention
failures and quality counts to `participants.csv`, and per-answer
`attention_passed` / `response_quality` to `answers.csv`.

### Verify without typing participant answers

From repository root, with the Python environment activated:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
bash human_study/scripts/check_v3.sh
python3 human_study/scripts/audit_webapp_native_parity.py
```

The first command is entirely offline: synthetic respondent/LLM/native
fixtures, idempotency and fault injection, 31-screen simulated session,
webapp parity unit tests, and frontend build. The second uses the **real
installed native GSS LSM model** to compare optimizer choices numerically
with the original webapp. Neither makes OpenAI calls or recruits humans.
See [TESTING.md](docs/TESTING.md) for interpretation and limitations.

Node 22.12+ is recommended for local frontend builds, matching the major
version of the Docker build. The previous Node 20.17 build completed despite
a Vite compatibility warning.

### Deployment boundary

Deploy only a new externally approved/versioned V3 instrument, with a distinct
study ID, code/model/pole hashes and reviewed consent. Check
`human_study/deploy/deploy.sh` in dry-run mode before `--execute`.
A successful offline test is **not** evidence that live OpenAI mappings,
Cloud Run/GCS/Firestore concurrency, ethics, or Prolific linkage have been
validated. See [production readiness](docs/PRODUCTION_READINESS.md).

---

## Historical M01/M02 participant pilot documentation

The material below describes the **earlier instrument-limited click-category
pilot**. Its 13+20+4 fixed bank, one-item answers, instrument generation, and
other requirements are **not the current V3 native-webapp design**.
It is retained so archived pilot runs remain interpretable.


Separate participant application for milestones M01/M02. The existing `webapp/`, simulator and public researcher API are unchanged. The normal study path reuses the real native GSS LSM, pole geometry, opinion-item classifier and DTAG's live LLM question generation and semantic validation. It accepts actual human category choices, never synthetic respondent answers.

No Google Cloud resources or paid Prolific traffic are created by local setup. See [SPEC.md](SPEC.md), [M01_REPORT.md](M01_REPORT.md) and [M02_REPORT.md](M02_REPORT.md).

## Local development

From the DTAG checkout, with the environment virtualenv active:

```bash
python -m pip install -r human_study/requirements.txt pytest httpx
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
export DTAG_MODEL_ROOT=/workspace/.cache/dtag/models
export DTAG_ASSETS_DIR=/workspace/.cache/dtag/assets

# Build for your Python ABI, retaining the bundled CPython 3.13 extension.
cmake -S native/lsm_runtime -B /workspace/.setup/dtag-native -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DPYTHON_EXECUTABLE="$(command -v python)"
cmake --build /workspace/.setup/dtag-native --parallel 4

python scripts/fetch_models.py gss/gss_2024
python -m human_study.instrument --out human_study/config/study.yaml
# Review the generated wording/categories/exclusions. This is not a validated instrument.

cd human_study/frontend
npm ci && npm run build
cd ../..
DTAG_ENV=local DTAG_LLM_BACKEND=mock PORT=8080 python -m human_study
```

The source wording in `config/study.example.yaml` is deliberately retained as extracted from the GSS 2024 map, including incomplete excerpts. The `source_text_incomplete` flag (25 items: 24 adaptive and one baseline) instructs the existing DTAG question LLM to produce a standalone neutral question from the available excerpt and exact response categories. Generated wording is NOT asserted to be a verbatim GSS question. Exact one-variable semantic remapping is required, and the source excerpt, displayed wording and attempt history are archived. If a known incomplete item cannot be generated or validated, the service returns a retryable 503 rather than showing the incomplete text. Unflagged baseline and outcome questions still display their canonical wording. This does not resolve ambiguous numeric scale labels or replace review of source semantics. The committed draft remains `reviewed: false`; copies created before this update must be refreshed to include the new flags.

For live question generation, set `DTAG_LLM_BACKEND=openai` and provide `OPENAI_API_KEY` securely through the process environment. The pinned LLM model is part of the instrument; the existing DTAG question generator and mapper run on every newly selected intervention question. No live-key test runs by default. The app serves `/study` and `/api/human/*`; it never mounts the research workbench. Local mode uses in-memory storage and loses its test sessions on process restart. Use only synthetic traffic in that mode.

For UI development when the native artifact is unavailable:

```bash
PYTHONPATH=human_study/backend DTAG_ENV=local DTAG_LOCAL_FIXTURE=1 \
  DTAG_LLM_BACKEND=mock PORT=8080 python -m human_study
```

The consent screen explicitly labels this as an internal mathematical software fixture, not native GSS or a research instrument. Staging/production reject this flag. Native scientific tests are separate from fixture/browser tests.

## Validation

```bash
pytest -q human_study/tests
DTAG_TEST_OFFLINE=1 pytest -q webapp/tests optimizer/tests
# Set DTAG_MODEL_ROOT to an installed GSS artifact to enable native integration.
cd human_study/frontend
PLAYWRIGHT_BROWSERS_PATH=/workspace/.cache/ms-playwright npx playwright install chromium
# Start the local fixture server separately, then:
PLAYWRIGHT_BROWSERS_PATH=/workspace/.cache/ms-playwright npm run test:e2e
```

The browser tests exercise all 37 fixture questions at mobile width, keyboard input, refresh, retry, completion and receipt resumption. The persistence suite injects crashes before/after answer acceptance, GCS create, export commitment and final export. Cloud-adapter contract tests do not replace validation against real Google Cloud services.

## Configuration and deployment

The full [config/study.example.yaml](config/study.example.yaml) was generated and validated against real native GSS 2024 categories: 13 baseline items, 28 eligible intervention items, three outcomes. It is marked `reviewed: false`. Regenerate from actual native categories with `instrument.py`; [config/instrument.example.yaml](config/instrument.example.yaml) records the proposed IDs and review requirements. Set `reviewed: true` only after investigator approval. A GCP-backed staging/production start fails without the reviewed instrument, native model/runtime, durable database/bucket, and stable cookie secret. The deployment script requires a separate reviewed instrument path and packages it explicitly.

| Setting | Behavior |
| --- | --- |
| `DTAG_ENV` | `local`, `staging`, `production`; default local |
| `DTAG_STUDY_CONFIG` | full instrument YAML; local default `human_study/config/study.yaml` |
| `DTAG_STUDY_ID`, `DTAG_MODEL_KEY`, `DTAG_MODEL_RELEASE`, `DTAG_OPENAI_MODEL` | if set, must match instrument; fixed GSS 2024/v0.2.1 in pilot |
| `DTAG_LLM_BACKEND` | `openai` or `mock`; production requires openai |
| `DTAG_GCS_BUCKET` | required private research bucket outside local mode |
| `DTAG_FIRESTORE_DATABASE` | `(default)` unless explicitly configured |
| `DTAG_PUBLIC_ORIGIN` | Exact browser-visible HTTPS service origin (e.g. result of `gcloud run services describe ... --format=value(status.url)`); required by deployment script and pinned to the deployed revision for CSRF validation behind reverse proxies |
| `DTAG_COOKIE_SECRET` | stable random secret, ≥32 characters; Secret Manager |
| `OPENAI_API_KEY` | required for openai; Secret Manager |
| `DTAG_LOCAL_FIXTURE` | `1` only for local/mock UI fixture |
| `PORT` | Cloud Run binding on `0.0.0.0`, default 8080 |
| `DTAG_CODE_COMMIT` | build injects reviewed source SHA for provenance |

After explicit authorization for an isolated billing-enabled GCP project:

```bash
export GCP_PROJECT='<isolated-project-id>'
export DTAG_GCS_BUCKET='<globally-unique-private-bucket>'
export GCP_REGION=us-east1  # suggestion, configurable
# Existing Cloud Run service: pin the browser-visible HTTPS origin explicitly.
export DTAG_PUBLIC_ORIGIN="$(gcloud run services describe dtag-human-pilot --project "$GCP_PROJECT" --region "$GCP_REGION" --format='value(status.url)')"
export DTAG_REVIEWED_CONFIG='/secure/path/reviewed.yaml'
bash human_study/deploy/provision.sh  # prints commands; does not provision
# After reviewing costs/IAM and explicit authorization:
# bash human_study/deploy/provision.sh --execute
# Supply versions securely for dtag-cookie-secret and dtag-openai-api-key in Secret Manager.
bash human_study/deploy/deploy.sh     # dry run; requires committed clean source
# bash human_study/deploy/deploy.sh --execute
```

APIs: Cloud Run, Firestore Native, Storage, IAM, Secret Manager, Artifact Registry, Cloud Build. The runtime identity receives Firestore user access in the isolated project, a bucket-scoped custom create/get/list role (no object deletion), and accessor access to the two secrets. The build identity receives Artifact Registry writer and logging/source-read permissions. Review/narrow source-bucket access after creating the dedicated build bucket. Deployers need service-account actAs and provisioning privileges. The scripts do not create a project, enable billing, set secret values, delete resources or recruit participants. They are not a general migration tool for existing resources; inspect pre-existing infrastructure instead of rerunning blindly.

The image uses the existing ABI-compatible Python 3.13 trixie base, verifies native import, builds React from a pinned lockfile, and honors `$PORT`. Models download with checksum verification into ephemeral cache; participant data never depend on that filesystem. Live processes and cookie secrets must not be regenerated on restart. Cloud Run starts at 2 vCPU/4 GiB, concurrency 2, max 2 instances and min 0; these are conservative staging settings requiring load/cost measurement. Set min 1 only after measuring cold starts and accepting its cost. The public URL is intended to be anonymous; configure Cloud Run proxy headers/ingress as appropriate and verify same-origin writes through its real HTTPS URL. Additional edge/distributed abuse protection is needed before recruitment.

After an authorized deployment, run `deploy/smoke.sh` with `STUDY_URL` set to the actual HTTPS URL and perform a synthetic full-session staging test. Inspect the private bucket and restart/resume behavior using the service account. No Cloud Run URL is claimed until those actions run.

## Research exports and deferred work

The app stores operational sessions plus question/event/idempotency/outbox subcollections in Firestore. GCS contains versioned study manifests, exact presented questions, accepted answers, events and `final.json`. Object names use anonymous IDs. No participant responses or GCP/OpenAI credentials belong in Git. Researcher export is a local ADC-authenticated CLI with no public HTTP endpoint:

```bash
python -m human_study.export --bucket "$DTAG_GCS_BUCKET" --study pilot-001 --out /secure/research/export-new
```

It writes participants, baseline, questions, answers, trajectories, outcomes CSVs plus provenance JSON. Output paths must be new and outside the checkout. Only finalized participants are included; incomplete participants remain available in the authoritative private object archive for a future audited export extension. No payment, rejection, attention adjudication, Prolific linkage, delayed follow-up or automated compensation decision is implemented. M03 needs reviewed eligibility/control/QC protocol, Prolific authentication/linkage/completion and a human reward-review workflow; none may reinterpret the internal receipt as a payment code.
