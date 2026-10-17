# DTAG developer guide

This guide is for people working on the DTAG code and assets. It covers the repository layout, the
runtime modules, the native runtime build, how to regenerate maps and poles, and the audits and tests.
For what the platform is and how to use it, see the [README](../README.md). For the web app's API and
internals, see [webapp/README.md](../webapp/README.md) and [webapp/HANDOFF.md](../webapp/HANDOFF.md).

## Repository layout

```text
DTAG/
  README.md, QUICKSTART.md      platform manual / five-minute start
  docs/                         developer guide, question-optimization research record
  webapp/                       browser workbench + FastAPI backend (dtag-web), tests, Docker
  optimizer/                    question-optimization package, one-step geometry, landscape, topics, tests
  scripts/                      runtime library (dtag_core, dtag_session, dtag_engine, ...),
                                model/map/pole toolchain, audits
  native/lsm_runtime/           bundled C++ native LSM runtime (pybind11) + prebuilt extension
  configs/
    dtag_config.yaml            run defaults and named respondent profiles
    eurodates.csv               Eurobarometer fieldwork-date registry
    model_coverage.json         countries/years each model covers (web recommender)
    suggested_questions.yaml    starter questions
    native_lsm_catalog.yaml     training catalog (scripts/train_native_lsm_models.py)
    optimizer_*.yaml            optimizer run configurations
  maps/                         semantic maps: gss/ (35), afromap/ (9), eurobarometer/ (207), WVS7 (1)
  assets/                       question sets, personas, polar vectors (ideology poles)
  poles/                        pole-discovery tool
  scratch/gss2018_pole_geometry/  research experiments (one-step geometry, push runs, poles)
  dtag/                         installed console commands (dtag-web, dtag-models, dtag-doctor)
  models/lsm/README.md          tracked placeholder only; models live outside Git
  data/                         local raw-data staging (documentation only in Git)
  outputs/, experiments/        generated outputs; ignored by Git
```

## Python environment

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="..."        # live generation only; tests use the mock LLM
```

## Bundled native LSM runtime

The minimal native C++ inference runtime is vendored under `native/lsm_runtime/`, so a fresh clone
does not need a sibling `lsm` repository. A prebuilt extension for CPython 3.13 on x86-64 Linux
(glibc ≥ 2.38) is committed. Anywhere else, build it once:

```bash
bash scripts/build_native_bindings.sh       # → native/lsm_runtime/python/dtag_lsm*.so
```

The binding persists for the whole session. When a model is loaded, its usable binary trees and
source-map dictionaries are cached once in a single `dtag_lsm.Runtime` object, and every prediction
and distance reuses it. If the extension is missing, DTAG exits with the build command instead of
loading code from elsewhere. See [native/lsm_runtime/README.md](../native/lsm_runtime/README.md) for
the runtime API (`predict_distributions`, `qdistance`, `distances_to_state`, `extension_distances`,
`split_columns`).

## Runtime modules

| Module | Role |
|---|---|
| `scripts/dtag_core.py` | Core library: maps, prefilters, LLM steps, model rows and distributions, geography, ideology. |
| `scripts/dtag_session.py` | One respondent: persona, anchors, semantic fallback, state, ideology. |
| `scripts/dtag_engine.py` | Model registry, catalog, profiles, Eurobarometer routing, sessions, push suggestions, landscape jobs. |
| `scripts/dtag_config.py` | Loads `configs/dtag_config.yaml` and resolves profiles (defaults < profile < overrides). |
| `scripts/pipeline_localized.py` | Deterministic geographic conditioning. |
| `scripts/dtag_recommend.py` | Who/where/when → model recommendation. |
| `scripts/model_backend.py` | Native LSM runtime interface (including the tree dependency graph). |
| `scripts/polar_vectors.py` | Wave-specific ideology pole resolution. |
| `scripts/eurobarometer_dates.py`, `scripts/eurobarometer_native.py` | Eurobarometer date routing and model/map helpers. |
| `scripts/fetch_models.py` | Public model download and verification (`dtag-models`). |
| `scripts/dtag_paths.py` | Repository and external model-store resolution. |
| `optimizer/session_push.py` | Next-question / push suggestions (one-step scoring at the session state). |
| `optimizer/landscape.py`, `optimizer/topics.py` | Decision landscape (incremental, progressive) and topic grouping. |
| `optimizer/one_step_geometry.py` | Exact one-step item × response geometry. |
| `webapp/backend/dtag_web/experiments.py` | Recorded recipes, rerun ×N, experiment folders and statistics. |

## Semantic map provenance

Every native model feature has a map row: `maps/gss/gss_YYYY_map.csv`,
`maps/afromap/afrobarometer_rN_map.csv`, `maps/wvs7_variable_question_map.csv` and
`maps/eurobarometer/ZAxxxx_map.csv`. When documentation is unavailable, the native variable name is
kept rather than dropping the feature.

Most Eurobarometer maps come from wave-specific GESIS documentation. Waves without usable
documentation use a semantic-union fallback built from the exact maps. Fallback rows keep these
provenance fields: `map_provenance`, `fallback_sources`, `fallback_n_sources`,
`fallback_consensus_fraction`, `fallback_support_similarity`, `fallback_context_f1` and
`fallback_resolution`. The `fallback_resolution` field takes one of `UNION_CONSENSUS`,
`UNION_SUPPORT_MATCH`, `UNION_CONTEXT_MATCH` or `UNRESOLVED_NATIVE`. An unresolved row can still run
using its native variable name, but it is never presented as exact documentation.

## Regenerating maps

```bash
python3 scripts/complete_native_maps.py      # everything: GSS, Afrobarometer R9, EB exact + fallback, WVS check, audit
```

Individual builders:

```bash
python3 scripts/build_all_gss_native_maps.py --force          # GSS: year semantics > cumulative docs > nearby-wave donor > native name
python3 scripts/getmap_dtag.py --codebook_pdf data/afrobarometer/codebooks/merged_r9_codebook_2.pdf \
  --model "$DTAG_MODEL_ROOT/afrobarometer/r9" --model-backend native_lsm --out maps/afromap/afrobarometer_r9_map.csv
python3 scripts/build_eurobarometer_maps.py --za ZA7575 --parse-timeout 600      # EB exact map
python3 scripts/build_eurobarometer_fallback_maps.py --report-only               # EB fallback: inspect
python3 scripts/build_eurobarometer_fallback_maps.py --build --force             # EB fallback: build
python3 scripts/audit_eurobarometer_assets.py
```

The native model's feature list is authoritative: undocumented variables stay in the map.

## Poles and coverage

```bash
python3 scripts/build_gss_polar_vectors.py      # assets/polar_vectors/gss/gss_YYYY_polar_vectors.csv for all 35 waves
python3 poles/discover_poles.py ...             # pole discovery
python3 scripts/build_model_coverage.py         # configs/model_coverage.json (streams each public archive's source maps)
```

## Model, map and pole toolchain

These scripts build or validate the assets the runtime loads. They are development utilities, not
alternative runtimes.

| Script | Purpose |
|---|---|
| `scripts/train_native_lsm_models.py` | Prepare survey CSVs and train native LSM models. |
| `scripts/build_gss_native_map.py`, `scripts/build_all_gss_native_maps.py` | GSS semantic maps. |
| `scripts/getmap_dtag.py` | Afrobarometer map builder. |
| `scripts/build_eurobarometer_maps.py`, `scripts/build_eurobarometer_fallback_maps.py` | Exact and semantic-union Eurobarometer maps. |
| `scripts/complete_native_maps.py` | All-family map completion. |
| `scripts/download_eurobarometer_codebooks_*`, `scripts/scan_gesis_dbk_ids.py` | Codebook retrieval. |
| `scripts/build_gss_polar_vectors.py`, `poles/discover_poles.py` | Ideology poles. |
| `scripts/build_model_coverage.py` | `configs/model_coverage.json`. |
| `scripts/package_public_models.py`, `scripts/publish_public_models.sh`, `scripts/rebuild_public_manifest.py` | Public model release. |
| `scripts/inventory_native_models.py`, `scripts/cleanup_native_lsm_models.py` | Installed-model inventory and trimming. |
| `scripts/audit_native_maps.py`, `scripts/audit_eurobarometer_assets.py` | Model and map audits. |
| `scripts/test_native_lsm_dtag.py`, `scripts/test_country_conditioning.py` | No-LLM runtime contract and country tests. |
| `scripts/check_dtag_readiness.py`, `scripts/audit_clean_repo.py` | Repository readiness (`dtag-doctor`). |
| `scripts/build_native_bindings.sh` | Build the native runtime extension. |

## Optimizer and research experiments

`optimizer/` holds the question-optimization package (`python -m optimizer ...`; see
[optimizer/README.md](../optimizer/README.md)) and the exact one-step geometry module:

```bash
python -m optimizer.one_step_geometry --model gss/gss_2018 --persona-ref CM --exclude-poles --top 10
python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona CM --direction right --n-items 6
```

The native evaluator re-scores about 7,000 (item, response) pairs in a few seconds. The research
record of the polarization and depolarization question sets is in
[QUESTION_OPTIMIZATION.md](QUESTION_OPTIMIZATION.md). The GSS 2018 pole-geometry experiments are in
`scratch/gss2018_pole_geometry/`.

## Tests and audits

```bash
python -m pytest -q                       # web app, engine, optimizer, core library (mock LLM, no key)
python -m pytest -q optimizer/tests       # optimizer only
python3 scripts/check_dtag_readiness.py --create-smoke-csv --overlap   # same checks as dtag-doctor
python3 scripts/audit_clean_repo.py       # no legacy runtime files or stale references
python3 scripts/inventory_native_models.py
python3 scripts/audit_native_maps.py --deep   # load every model; expect 252 models, 252 maps, 0 missing/bad/overlap
```

Native-model tests run when the models are installed and are skipped otherwise.

## Commands

| Command | Purpose |
|---|---|
| `dtag-web` / `webapp/run.sh` | Browser workbench and HTTP API. |
| `dtag-models` | Download and verify public native models. |
| `dtag-doctor` | Readiness and clean-surface checks. |
| `python -m optimizer ...` | Question optimization. |
| `python -m optimizer.one_step_geometry ...` | Exact one-step item/response geometry. |

The former command-line runtime (`dtag --profile`, `scripts/pipeline.py`, `run_grid.py`,
`postprocess.py`, `bin/*.sh`) has been retired. It remains in the Git history of the `dev` branch.
