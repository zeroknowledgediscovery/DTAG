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
- **Attention checks.** `kind: instructed_token` ("include the word cobalt",
  LLM-worded) and `kind: factual` (obvious-answer question shown verbatim,
  passes if the reply contains any `accepted_answers` as a whole word). They
  never touch the LSM state.
- **Answer-quality flags** (recorded, never scored): `fast` (answered within
  `quality.fast_seconds`), `short` (< `quality.short_words` words), and
  `duplicate_of` (≥ `quality.duplicate_similarity` similar to an earlier answer).
  Unintelligible text is already refused by the mapper and must be rewritten.
- **Prolific linkage.** Set the Prolific study URL to
  `https://<service>/study?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}`.
  Outside local mode a PID is required. Each PID gets one session
  (HMAC of study ID + PID, keyed by `DTAG_COOKIE_SECRET`), so a participant who
  loses cookies resumes rather than restarts.
- **Three Prolific completion paths.** Create a distinct fixed, opaque code
  for `completion_code` (approve/pay the advertised full study reward),
  `review_code` (manual review, **not** automatic rejection or a reduced
  payment), and `no_consent_code` (Prolific's **No consent → Request a return**
  path, without a study reward). These codes are shared across participants,
  not generated per person. Participants with ≥ `attention_fail_threshold`
  (default 2) failed checks receive the review code; this is a *flag* and
  any compensation decision must follow Prolific's policy. The consent-decline
  page provides a separate return URL. Staging/production and `deploy.sh`
  refuse the `CHANGEME` placeholders.
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
