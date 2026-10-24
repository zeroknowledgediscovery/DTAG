# M02 local implementation and verification

Branch: `experiment/prolific-human-study`.
Base: `b6f20cf5e87af9d23ef947de43355934da17980c` (`origin/dev`, freshly fetched).
Validated runtime implementation: `7ae6a03b31cfe2a7aec20c96d080933a535bd735`.
The final report/test-only commit follows that runtime commit; its exact SHA is returned in the completion message and by `git rev-parse HEAD`. A committed report cannot contain its own commit hash.

Implemented a separate participant application, native human-state adapter, four policies, live DTAG question generation/mapper, immutable question presentation, signed anonymous sessions, transactional Firestore operational state, mandatory GCS outbox reconciliation, completion receipts, private investigator export, React UI, container and parameterized deployment tooling. Existing simulator source, dependency declarations and lockfiles were not modified. Local/mock and real-native GSS checks ran; **live OpenAI and deployed Google Cloud acceptance criteria are not claimed complete**.

## Architecture and file changes

| File under `human_study/` | Responsibility |
| --- | --- |
| `backend/human_study/__init__.py` | Resolve shared repository imports without copying the scientific implementation |
| `backend/human_study/__main__.py` | Single-process server honoring `0.0.0.0:$PORT` |
| `backend/human_study/adapter.py` | Native World, strict qdistance index, exact incremental scores, locks, artifact/map/pole/binary/source provenance |
| `backend/human_study/state.py` | Baseline-only initialization, exact observed answers, missingness, retained anchors and replay validation |
| `backend/human_study/policy.py` | Shared eligible pool, expected-delta right/left/neutral and persisted uniform random selection |
| `backend/human_study/questions.py` | Existing DTAG neutral LLM wording and one-item mapping, bounded retries and auditable fallback |
| `backend/human_study/study_config.py` | Strict versioned instrument/item/choice contracts, disjoint banks and configuration hashing |
| `backend/human_study/instrument.py` | Construct an unreviewed 13-item baseline and separate outcomes/interventions from real native labels and semantic text |
| `backend/human_study/service.py` | Consent, assignment after baseline, question claims, validated answers, outbox reconciliation and finalization |
| `backend/human_study/storage.py` | CAS/archive interfaces and explicit local-only memory adapters |
| `backend/human_study/storage_firestore.py` | Atomic multi-document CAS and stable reads, including 128-bit RNG serialization |
| `backend/human_study/storage_gcs.py` | Private-bucket readiness, create-only writes, checksum verification and exact conflict comparison |
| `backend/human_study/security.py` | Signed HttpOnly/Secure/SameSite cookies and bounded per-instance throttling |
| `backend/human_study/schemas.py` | Strict public request whitelist, no policy/model/persona/key controls |
| `backend/human_study/app.py` | Isolated public endpoints, same-origin writes, body limits, minimal health/readiness, frontend serving and fail-closed startup |
| `backend/human_study/export.py` | Private ADC-authenticated GCS-to-CSV investigator CLI; finalized sessions only |
| `backend/human_study/local_fixture.py` | Explicitly labelled mathematical UI fixture, rejected outside local/mock mode |
| `frontend/src/main.tsx` | Consent, one prompt at a time, native choices, idempotent retry, progress and internal receipt |
| `frontend/src/style.css` | Mobile layout, focus states, keyboard-operable options and accessible labels |
| `frontend/index.html` | Participant page shell |
| `frontend/package.json` | Pinned frontend tools and React dependencies |
| `frontend/package-lock.json` | Reproducible npm installation |
| `frontend/tsconfig.json` | Strict TypeScript checks |
| `frontend/vite.config.ts` | Frontend build and local API proxy |
| `frontend/playwright.config.ts` | Browser-test runner with configurable local/container URL |
| `frontend/e2e/study.spec.ts` | Mobile keyboard flow, refresh/resume, receipt and request-failure retry |
| `tests/conftest.py` | Scientific fixtures and isolated configuration |
| `tests/test_human_engine.py` | Synthetic-path guards, reference scores, 20-step replay, exclusions, LLM mapping/fallback and native GSS integration |
| `tests/test_human_api.py` | Anonymous isolation, signed ownership, public API bounds, docs isolation and fail-closed settings |
| `tests/test_persistence.py` | Full flow, concurrency, crashes at each outbox boundary, restart, finalization and export contract |
| `tests/test_cloud_adapters.py` | GCS generation/checksum/integrity and Firestore CAS/RNG adapter contracts |
| `tests/test_container_flow.py` | Opt-in external-container health/assets/port and complete fixture session |
| `Dockerfile` | Existing Python 3.13/trixie ABI, pinned frontend build, native import and unprivileged entrypoint verification |
| `Dockerfile.dockerignore` | Exclude credentials, local instruments/data, caches and Git metadata from context |
| `requirements.txt` | Separate GCP storage/database/security dependencies, reusing existing DTAG requirements |
| `deploy/provision.sh` | Dry-run-first isolated-project APIs, private bucket, Firestore, IAM, secrets and registry provisioning commands |
| `deploy/deploy.sh` | Reviewed instrument gate, clean tracked-source archive, Cloud Build and capped Cloud Run deployment commands |
| `deploy/cloudbuild.yaml` | Parameterized image build with exact source SHA |
| `deploy/smoke.sh` | Read-only probes for a later explicitly authorized HTTPS deployment |
| `config/instrument.example.yaml` | Proposed native IDs and review requirements; not a loadable or validated instrument |
| `config/study.example.yaml` | Full generated instrument validated against the real native GSS categories/map; `reviewed=false` |
| `schema/final.schema.json` | Sanitized final-object schema without participant records |
| `README.md` | Local/native/LLM/test/container/deploy/export commands, settings and outstanding review |
| `SPEC.md` | Protocol assumptions, scientific boundaries, state/selection/persistence/security contracts |
| `M01_REPORT.md` | Engine decisions, native/network limitation and initial test evidence |
| `M02_REPORT.md` | This implementation/verification record |
| `.gitignore` | Keep generated UI, browser evidence and local instrument out of Git |

Deliberate differences from the proposal: the full native instrument is generated rather than guessing source-map categories; configuration and question IDs are hashed; versioned manifests use `manifests/<config_hash>.json`; the local fixture allows UI development without a model download; no stratification/control-question/payment workflow is claimed. Incomplete sessions are safely archived per event but the CSV CLI currently includes finalized sessions only. The existing core can silently return canonical wording on LLM failure, so canonical returns are flagged as possible fallbacks rather than falsely asserting a successful live rewrite.

## Tests and reproducible commands

The virtualenv is `/workspace/.venv`. Workspace-local caches are required on this machine because the home directory is read-only. Set `DTAG_WEB_DATA_DIR=/workspace/.cache/dtag/webapp` and `DTAG_ASSETS_DIR=/workspace/.cache/dtag/assets` for existing tests; do not modify their source to work around that environment constraint.

```
# Human/backend, existing webapp/optimizer, and opt-in container suite:
DTAG_TEST_CONTAINER_URL=http://127.0.0.1:8081 \
DTAG_WEB_DATA_DIR=/workspace/.cache/dtag/webapp \
DTAG_ASSETS_DIR=/workspace/.cache/dtag/assets DTAG_TEST_OFFLINE=1 \
  /workspace/.venv/bin/pytest -q human_study/tests webapp/tests optimizer/tests --disable-warnings -rs

# Frontend:
cd human_study/frontend
npm ci && npm run build
DTAG_TEST_BROWSER_URL=http://127.0.0.1:8081 \
PLAYWRIGHT_BROWSERS_PATH=/workspace/.cache/ms-playwright npm run test:e2e
```

Frontend compilation/build passed. Both Playwright tests passed against the running container: 37-question mobile keyboard flow including refresh and receipt resumption; simulated network failure with retry and preserved wording. Screenshot evidence is generated locally at `human_study/frontend/test-results/mobile-receipt.png` and deliberately not committed.

The initial combined backend/container run passed **174 tests, 15 skipped in 19.08 seconds** while the model was blocked. After GSS installation, the full regression command with `DTAG_MODEL_ROOT=/workspace/.cache/dtag/models`, **without** `DTAG_TEST_OFFLINE`, passed **185 tests, four skipped in 92.90 seconds**. See `/workspace/.setup/native-final-tests.log`. Those four skips are the stopped external-container test (already independently passed), missing non-GSS coverage and Afrobarometer R5, and uninstalled GSS 2018. They do not skip the GSS 2024 integration tier.

Four further native recorded-answer replay tests were then added, one per policy. The final engine run `DTAG_MODEL_ROOT=/workspace/.cache/dtag/models DTAG_ASSETS_DIR=/workspace/.cache/dtag/assets /workspace/.venv/bin/pytest -q human_study/tests/test_human_engine.py` passed **12 tests in 59.67 seconds**. Each new test records 20 exact categorical fixture choices, compares the updated index with native qdistance, and reconstructs/recomputes all selections and indices from the records. The separate opt-in container test passed **1 test**, and both browser tests passed against that container. These are separate runs; their overlapping counts must not be added as independent tests.

The second repository, `/workspace/lsm` at `f4a19c8b77c6e6b79a66d3823644b7ff189310a1`, was built with CMake Release, profiling off, Python bindings on, terminal logging on, Python 3.12 and four build workers. Boost was extracted locally from signed Debian package indexes. Results:

```
PYTHONPATH="$PWD/bin" /workspace/.venv/bin/python -m pytest -q tests/integration
# 9 passed
PYTHONPATH="$PWD/bin" /workspace/.venv/bin/python tests/high_cardinality_qsample_alphabet.py
# PASS, 10,000 draws checked
/workspace/.venv/bin/python tests/hong/check_source_manifest.py
# PASS, exact=34, registered_patches=8
/workspace/.venv/bin/python tests/hong/test_wide_group_index_contract.py
# PASS
LSM_THREADS=2 bash tests/hong/run_wide_csv_regression.sh
# PASS, 1034 columns, target [1000,1001), 2 threads
```

The reusable installation script at `/workspace/.setup/install.sh` was rerun successfully with `DTAG_SKIP_MODEL_FETCH=1`: dependency refresh, both native builds, frozen npm install and frontend build are repeatable. This explicit skip does not establish GSS readiness.

## Container evidence and resolved failures

```
DOCKER_CONFIG=/workspace/.setup/docker docker build --progress=plain \
  -f human_study/Dockerfile --build-arg DTAG_CODE_COMMIT="$(git rev-parse HEAD)" \
  --build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY \
  --secret "id=cloud_ca,src=$SSL_CERT_FILE" -t dtag-human-study:local .

DOCKER_CONFIG=/workspace/.setup/docker docker run -d --name dtag-human-container-check \
  -p 127.0.0.1:8081:9090 -e DTAG_ENV=local -e DTAG_LOCAL_FIXTURE=1 \
  -e DTAG_LLM_BACKEND=mock -e PORT=9090 dtag-human-study:local
```

The build passed; runtime image SHA256: `eb8d75d540fdd36961957c1a06377749b7d6766c5841f78a7a4ba9ff3ce17299`. Native import succeeds as UID 10001 using `dtag_lsm.cpython-313-x86_64-linux-gnu.so`. The app serves frontend/API/health/readiness on container port 9090, demonstrating `$PORT` handling. The HTTP smoke test completes consent, all fixture phases and receipt retrieval. Browser tests passed against that same container. Fixture session state is intentionally in memory; these results do not demonstrate real Firestore/GCS durability.

Initial container attempts exposed (and corrected) read-only Docker client state, missing build proxy/CA propagation, and copied source permissions that prevented the unprivileged entrypoint from loading. BuildKit receives the environment's existing CA through a temporary secret mount; TLS verification remains on and the CA mount is not baked into the image. Imports are now checked after switching to the runtime user. Combined pytest collection initially exposed generic test-module/conftest names; human tests were renamed and helper imports made explicit. A later invocation omitted workspace-local cache variables; rerunning with the documented variables passed. Existing simulator source was not changed.

## Archive contract and deployment status

See `schema/final.schema.json`. A sanitized outline (placeholders, not participant data):

```json
{
  "schema_version": "1", "kind": "session_final",
  "study_id": "<configured-study>", "session_id": "<anonymous-random-id>",
  "policy": "<server-only-arm>", "baseline_index": 0.0, "final_index": 0.0,
  "questions": [{"question_id": "<immutable-id>", "phase": "intervention",
    "target_variable": "<validated-native-id>", "original_wording": "<canonical-item>",
    "displayed_wording": "<exact-LLM-question-or-logged-fallback>",
    "choices": [{"native_value": "<exact-native-category>", "display_label": "<reviewed-label>"}],
    "response_value": "<actual-submitted-choice>",
    "index_result": {"index_before": 0.0, "index_after": 0.0,
      "predicted_model_delta": 0.0, "observed_conditional_index_delta": 0.0}}],
  "source_objects": ["<private-object-reference>"], "provenance": {"code_commit": "<exact-SHA>"},
  "content_sha256": "<canonical-content-hash>"
}
```

Provision and deploy scripts were syntax-checked and executed in **dry-run mode with placeholders and a synthetic reviewed fixture**. No GCP project was inferred, no resources provisioned, no secrets requested/created, no image pushed to GCP, no Cloud Run service deployed, no live OpenAI call made, and no Prolific participants recruited. There is no Cloud Run URL to report. Required APIs/IAM/Secret Manager settings and conservative starting caps are documented in README and scripts; they require infrastructure/security/cost review before authorized execution.

## Outstanding validation and limits

The initial `storage.googleapis.com` HTTP 403 was resolved after the environment's network policy changed. A retry installed GSS 2024 with the existing SHA256-verifying downloader. `python -m human_study.instrument --out human_study/config/study.yaml` produced 44 native-validated items (13 baseline, 28 intervention, three outcomes); the generated draft is also saved as `config/study.example.yaml` with `reviewed=false`. Real-native index equality and withheld-outcome predictions passed. A 36-answer native GSS flow using `QuestionLLM(..., 'mock')` and the real native adapter completed through consent, baseline, assignment, 20 adaptive questions, three outcomes and receipt. It created 75 immutable local archive objects. These were synthetic recorded choices, not responses sampled from the model. No verification was bypassed.

Live LLM wording/mapping, Firestore transactional behavior against a deployed database, private GCS permissions/reconciliation against a real bucket, Cloud Run restarts/autoscaling and latency/cost remain unverified. Unit adapter contracts and shared-store restart simulations cannot replace a staging test. The conservative instrument, ethics/eligibility/retention/support wording, model/data license and baseline/outcome validity require investigator review. Frozen prompt/code/model versions must be retained for interrupted sessions; version mismatches fail safely instead of silently reinterpreting data.

M03 remaining scope: Prolific identity linkage and authentication, approved eligibility/control/QC protocol, completion-code/redirect integration, and human compensation review/reconciliation. No payment entitlement decision, rejection engine, delayed follow-up or claim of human persuasion is included here.
