# Human-response DTAG pilot

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
