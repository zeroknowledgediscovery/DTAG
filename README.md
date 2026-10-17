# DTAG — Digital Twin Anchored Generation

DTAG is a survey-grounded generative system built on native Large Science Models (LSMs). It conditions a learned survey-state model on a persona, time, and place where supported; maps natural-language questions to survey variables; predicts conditional response distributions; and uses those distributions to anchor generated answers.

> **Full platform manual: [docs/MANUAL.md](docs/MANUAL.md)**. It covers what DTAG is and is for, how to run
> and use the web app, every workbench feature, where the models live and how they are downloaded,
> the other information DTAG uses, and full survey coverage.
>
> Developed by ZeD Lab, University of Kentucky · contact: ishanu_ch@uky.edu

This branch is the clean native-LSM implementation. It contains no Quasinet runtime, no legacy model files, and no RC1 compatibility surface.

Current validated native inventory:

| Survey family | Native models | Semantic maps |
|---|---:|---:|
| GSS | 35 | 35 |
| Afrobarometer | 9 | 9 |
| WVS7 pooled | 1 | 1 |
| Eurobarometer | 207 | 207 |
| **Total** | **252** | **252** |

The deep audit verifies zero missing maps, zero bad maps, and complete model-map feature overlap across all 252 native models.

## Web app quick start

```bash
python3.13 -m venv dtag-env && source dtag-env/bin/activate
pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"
export OPENAI_API_KEY="sk-..."      # or run with DTAG_LLM_BACKEND=mock to try it without a key
dtag-web                            # then open http://127.0.0.1:8000
```

Describe a respondent (who / where / when), let DTAG pick and load the matching
native survey model, start the respondent and ask questions.
Step-by-step guide: **[webapp/QUICKSTART.md](webapp/QUICKSTART.md)** ·
full reference: [webapp/README.md](webapp/README.md).

What the workbench does (details in [docs/MANUAL.md §10](docs/MANUAL.md#10-the-web-workbench-feature-by-feature)):

- **Survey-anchored answers** with a *Model evidence* panel: variables, wording, native distribution, anchor, state updates.
- **Automatic model choice** from who/where/when across GSS, WVS7, Afrobarometer and Eurobarometer, downloaded on demand.
- **Ideology index and trajectory** (GSS), plus **next-question suggestions** for every survey, with
  realistic / validated / push modes and auto-push.
- **Decision landscape**: a live doughnut or terrain map of every predicted answer and how each answer reshapes it.
- **Question sequences**, **two respondents side by side**, and **experiments** (record a recipe, rerun ×N,
  bootstrap statistics, per-step data saved to `experiments/`).
- **Exports**: full session log ZIP / JSON / CSV, and figures as SVG / PNG / PDF; resizable columns; light/dark theme.

## Quick start (models)

Install DTAG from the public GitHub branch (no manual clone required) and fetch the native
model(s) you need from the public, SHA256-verified model store:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"

dtag-models gss/gss_2024          # one model
dtag-models --list                # public catalog
dtag-models --family gss          # one survey family
dtag-models --all                 # the complete corpus
```

Models are downloaded once, decompressed into the local cache and reused. The default cache is
`~/.cache/dtag/models/`. The web app can also install missing models on demand.

### Web application

The installation includes a browser workbench and HTTP API:

```bash
export OPENAI_API_KEY="..."
dtag-web                      # http://127.0.0.1:8000  (API docs at /docs)
```

Select or build a respondent (who / where / when), let DTAG fetch any missing
public model, ask questions, and inspect the native-LSM evidence behind every
answer: selected survey variables, response distributions, anchors, state
updates, conditioning, ideology trajectory, and JSON/CSV exports. From a
source checkout use `cd webapp && ./run.sh`, or `docker compose up` in
`webapp/`. See [`webapp/README.md`](webapp/README.md).

The web application runs the respondent implementation in `scripts/dtag_session.py`, driven by
`scripts/dtag_engine.py`. The former command-line runtime (`dtag --profile ...`,
`scripts/pipeline.py`, `bin/*.sh`) is archived; see [Archive](#archive).

On compatible CPython 3.13 x86-64 Linux systems, DTAG uses the bundled prebuilt native LSM extension. Other supported environments can rebuild the native extension from the source shipped with the installed repository tree (`bash scripts/build_native_bindings.sh`).

## Architecture

DTAG separates three layers:

1. **Native LSM model** — learned conditional structure and state geometry.
2. **Semantic map** — model variable to survey question/label text.
3. **Generation layer** — maps a user question into survey variables, conditions the digital twin, predicts response distributions, and generates an answer anchored to those distributions.

A DTAG state is therefore a survey-variable state constrained by the native LSM, not merely free-form conversational history.

## Repository layout

```text
DTAG/
  webapp/                       browser workbench + FastAPI backend (dtag-web), tests, Docker
  optimizer/                    question-optimization package, one-step geometry, tests
  scripts/                      runtime library (dtag_core, dtag_session, dtag_engine, ...),
                                model/map/pole toolchain, audits
  native/lsm_runtime/           bundled C++ native LSM runtime (pybind11) + prebuilt extension
  configs/
    dtag_config.yaml            native model/map profiles
    eurodates.csv               Eurobarometer fieldwork-date registry
    model_coverage.json         countries/years each model covers (web recommender)
  maps/
    gss/                        35 GSS per-wave maps
    afromap/                    Afrobarometer R1-R9 maps
    eurobarometer/              207 ZA-specific maps
    wvs7_variable_question_map.csv
  assets/                       question sets, personas, polar vectors (ideology poles)
  poles/                        pole-discovery tool
  scratch/gss2018_pole_geometry/  research experiments (one-step geometry, push runs, poles)
  dtag/                         installed console commands (dtag-web, dtag-models, dtag-doctor)
  models/lsm/README.md          tracked placeholder only; models live outside Git
  data/                         local raw-data staging (documentation only in Git)
  archive/                      deprecated command-line runtime and launchers (not maintained)
  outputs/                      generated outputs; ignored by Git
```

## Native model location

By default DTAG looks under:

```text
models/lsm/
```

A complete store has:

```text
models/lsm/
  gss/
    gss_1972/
    ...
    gss_2024/
  afrobarometer/
    r1/
    ...
    r9/
  wvs/
    wvs7_pooled/
  eurobarometer/
    ZAxxxx_v.../
```

Every native model directory must contain at least:

```text
source_maps/
trees/binary/
```

For a clean checkout, keep the large model corpus outside the repository and set:

```bash
export DTAG_MODEL_ROOT="$HOME/Dropbox/ZED/Models/DTAG_LSM"
```

or another local/cache path such as:

```bash
export DTAG_MODEL_ROOT="$HOME/.cache/dtag/models"
```

The external root contains the family directories directly:

```text
$DTAG_MODEL_ROOT/
  gss/
  afrobarometer/
  wvs/
  eurobarometer/
```

When `DTAG_MODEL_ROOT` is unset, DTAG uses an already-populated `<repo>/models/lsm`, otherwise `~/.cache/dtag/models`.

## Bundled native LSM runtime

DTAG now vendors the minimal native C++ inference runtime directly under:

```text
native/lsm_runtime/
```

A fresh clone therefore does **not** require a sibling `lsm` repository.

Build the Python extension once:

```bash
bash scripts/build_native_bindings.sh
```

The build creates:

```text
native/lsm_runtime/python/dtag_lsm*.so
```

DTAG discovers this extension automatically.

The binding is session-persistent: when a DTAG model is loaded, its usable
binary trees and source-map dictionaries are loaded/cached once and retained by
a single C++ `dtag_lsm.Runtime` object for the lifetime of that interactive
session. Per-question predictions and ideology distances reuse the same
in-memory model rather than reopening the model files.

The clean native branch does not use external inference bindings. If the
bundled extension has not been built, DTAG exits with the build command rather
than silently loading code from another repository.

## Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Live generation also requires:

```bash
export OPENAI_API_KEY="..."
```

The deterministic validation suite does not require an OpenAI call.

## Tests

```bash
python -m pytest -q                 # web app, engine, optimizer, core library
python -m pytest -q optimizer/tests # optimizer only
```

Native-model tests run when the corresponding models are installed and are skipped otherwise;
everything else uses the mock LLM (`DTAG_LLM_BACKEND=mock`) and needs no OpenAI key.

## Repository readiness

Canonical readiness check:

```bash
python3 scripts/check_dtag_readiness.py   --create-smoke-csv   --overlap
```

It checks source files, Python syntax, packages, native bindings, configured model paths, maps, selected model-map overlap, question sets, polar vectors, and Eurobarometer coverage/provenance.

## Clean native-only checkout audit

After switching to this branch, verify that no legacy runtime files or local
top-level model folders remain:

```bash
python3 scripts/audit_clean_repo.py
```

This checks obsolete paths, stale legacy source references, required clean
surface files, and Python syntax.

## Complete native audit

Inventory installed native models:

```bash
python3 scripts/inventory_native_models.py
```

Audit all maps:

```bash
python3 scripts/audit_native_maps.py
```

Deep audit loading every model:

```bash
python3 scripts/audit_native_maps.py --deep
```

Expected result:

```text
native models: 252
maps present:  252
missing maps:  0
bad maps:      0
overlap issues:0

PASS: native DTAG map surface is complete.
Expected/verified inventory: 35 GSS + 9 Afrobarometer + 1 WVS + 207 Eurobarometer = 252
```

## Profiles

Named respondent profiles (model, map, persona, optional country/continent/year and run
settings) live in `configs/dtag_config.yaml` under `interactive_profiles`. The web app lists them
(`GET /api/profiles`) and resolves them with `scripts/dtag_config.py`
(defaults < profile < request overrides). Representative profiles:

```text
gss2018_wf  gss2018_cm  gss2022_wf  gss2022_cm  gss2024_wf  gss2024_cm
wvs7_india_2017  afrobarometer_r5_nigeria  afrobarometer_r5_ghana
```

## Runtime modules

| Module | Role |
|---|---|
| `optimizer/session_push.py`, `optimizer/landscape.py`, `optimizer/topics.py` | next-question / push suggestions, decision landscape, topic grouping |
| `webapp/backend/dtag_web/experiments.py` | recorded recipes, rerun ×N, experiment folders and statistics |
| `scripts/dtag_core.py` | core library: maps, prefilters, LLM steps, model rows/distributions, geography, ideology |
| `scripts/dtag_session.py` | one respondent: persona, anchors, semantic fallback, state, ideology |
| `scripts/dtag_engine.py` | model registry, catalog, profiles, Eurobarometer routing, sessions (web + API) |
| `scripts/dtag_config.py` | load `configs/dtag_config.yaml` and resolve profiles |
| `scripts/pipeline_localized.py` | deterministic geographic conditioning (patches `dtag_core.build_forced_assignments`) |
| `scripts/dtag_recommend.py` | who/where/when → model recommendation |
| `scripts/model_backend.py` | native LSM runtime interface |
| `scripts/polar_vectors.py` | wave-specific ideology pole resolution |
| `scripts/eurobarometer_dates.py`, `scripts/eurobarometer_native.py` | Eurobarometer date routing and model/map helpers |
| `scripts/fetch_models.py` | public model download/verification (`dtag-models`) |
| `scripts/dtag_paths.py` | repository/external model-store resolution |

## Persona, time, and place

A profile supplies a persona plus optional structured time/location constraints. Persona attributes become explicit model-state constraints only when the selected survey model contains compatible variables and support.

Conceptually:

```text
persona + time + place + current survey state
                  ↓
        native LSM conditionals
                  ↓
       survey-anchored generation
```

### Place

DTAG uses geography in this order when supported:

1. direct categorical country variable (a variable named *country*; for Eurobarometer also the ISO 3166 `isocntry` variable and, in older waves, the map-labelled `NATION` variable);
2. WVS-style geographic proxy fields such as coordinates;
3. contextual localization if no deterministic survey variable exists.

Afrobarometer deterministic country conditioning can be tested with:

```bash
python3 scripts/test_country_conditioning.py
```

### Time

Time handling is family-specific.

- **GSS:** model selection is wave-specific.
- **WVS7:** year may additionally be conditioned if the pooled model exposes a compatible field.
- **Eurobarometer:** a calendar date is routed to a fieldwork wave.

## Eurobarometer date + country

In the web app a Eurobarometer respondent is specified by a calendar date and a country; the
engine routes the date to a fieldwork wave using the registry `configs/eurodates.csv`
(`scripts/eurobarometer_dates.py`) and resolves the wave's native model and map
(`scripts/eurobarometer_native.py`). An explicit ZA wave can also be chosen.

A year alone is deliberately not assumed to identify a unique wave because several Eurobarometers may occur in one year.

### Eurobarometer routing assumptions

- A date selects a discrete survey wave; there is no continuous interpolation between waves.
- If multiple ordinary fieldwork intervals cover a date, routing should remain conservative.
- Broad cumulative/trend files are not silently substituted for ordinary waves.
- Country is applied after/with wave selection and is not universally sufficient to disambiguate overlapping waves.

## Semantic map provenance

Every native model feature has a map row.

Canonical locations:

```text
maps/gss/gss_YYYY_map.csv
maps/afromap/afrobarometer_rN_map.csv
maps/wvs7_variable_question_map.csv
maps/eurobarometer/ZAxxxx_map.csv
```

When documentation is unavailable, the native variable name is retained rather than dropping the model feature.

### Eurobarometer fallbacks

There are 207 Eurobarometer models and 207 maps. Most maps are derived from wave-specific GESIS documentation. Waves without usable model-specific documentation use a semantic-union fallback built from the exact maps.

Fallback rows retain provenance fields such as:

```text
map_provenance
fallback_sources
fallback_n_sources
fallback_consensus_fraction
fallback_support_similarity
fallback_context_f1
fallback_resolution
```

Resolution classes include:

```text
UNION_CONSENSUS
UNION_SUPPORT_MATCH
UNION_CONTEXT_MATCH
UNRESOLVED_NATIVE
```

An unresolved row remains runnable using its native variable name. It is not represented as exact documentation.

## Regenerating all maps

One command:

```bash
python3 scripts/complete_native_maps.py
```

It orchestrates:

- all 35 GSS maps;
- Afrobarometer R9 from its real codebook;
- missing exact Eurobarometer maps;
- missing union-fallback Eurobarometer maps;
- WVS map verification;
- final all-family audit.

### GSS

```bash
python3 scripts/build_all_gss_native_maps.py --force
```

The GSS builder resolves text using:

1. year-specific semantics when available;
2. cumulative GSS documentation;
3. exact-name nearby-wave donor semantics;
4. native feature name as final fallback.

### Afrobarometer

Example R9 build:

```bash
python3 scripts/getmap_dtag.py   --codebook_pdf data/afrobarometer/codebooks/merged_r9_codebook_2.pdf   --model "$DTAG_MODEL_ROOT/afrobarometer/r9"   --model-backend native_lsm   --out maps/afromap/afrobarometer_r9_map.csv
```

The native model feature list is authoritative; undocumented variables remain in the map.

### Eurobarometer exact map

```bash
python3 scripts/build_eurobarometer_maps.py   --za ZA7575   --parse-timeout 600
```

### Eurobarometer fallback maps

Inspect:

```bash
python3 scripts/build_eurobarometer_fallback_maps.py --report-only
```

Build:

```bash
python3 scripts/build_eurobarometer_fallback_maps.py   --build   --force
```

Audit:

```bash
python3 scripts/audit_eurobarometer_assets.py
```

## GSS ideology tracking

Compatible GSS profiles can use:

```text
assets/polar_vectors/polar_vectors.csv
```

The current state is evaluated relative to reference states using native LSM qdistance. If compatible polar vectors are unavailable, DTAG still runs normally; ideology scoring is simply omitted.

## Semantic fallback modes

Runtime modes include:

```text
off
answer_only
update_state
```

Configured default: `update_state` (with response mode `draw`).

- `off`: no semantic fallback when direct mapping fails.
- `answer_only`: fallback assists response grounding but does not change persistent state.
- `update_state`: accepted bridge anchors update persistent state (each answer records which case applied).

## Stateful sequences

DTAG can preserve survey-state assignments across a question sequence. When state updates are enabled, an answer may alter subsequent native-LSM conditionals.

The web app supports ordered question sequences for controlled experiments.

## Optimizer and research experiments

`optimizer/` contains the question-optimization package (`python -m optimizer ...`; see
[`optimizer/README.md`](optimizer/README.md)) and the exact one-step geometry module:

```bash
# every askable item x every response: Delta J, P(response), mu, argmax/argmin
python -m optimizer.one_step_geometry --model gss/gss_2018 --persona-ref CM --exclude-poles --top 10
```

The native evaluator re-scores ~7k (item, response) pairs in a few seconds (incremental
`Runtime.extension_distances`; see `native/lsm_runtime/README.md`).

Experiments and findings live in `scratch/gss2018_pole_geometry/`:

```bash
python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona CM --direction right --n-items 6
```

(`ONE_STEP_FINDINGS.md`, `ONE_STEP_REPORT.md`, `Experiment.md`).

## Model, map and pole toolchain

These scripts build or validate the assets the runtime loads; they are development utilities,
not alternate runtimes.

| Script | Purpose |
|---|---|
| `scripts/train_native_lsm_models.py` | prepare survey CSVs and train native LSM models |
| `scripts/build_gss_native_map.py`, `scripts/build_all_gss_native_maps.py` | GSS semantic maps |
| `scripts/getmap_dtag.py` | Afrobarometer map builder |
| `scripts/build_eurobarometer_maps.py`, `scripts/build_eurobarometer_fallback_maps.py` | exact / semantic-union Eurobarometer maps |
| `scripts/complete_native_maps.py` | all-family map completion |
| `scripts/download_eurobarometer_codebooks_*`, `scripts/scan_gesis_dbk_ids.py` | codebook retrieval |
| `scripts/build_gss_polar_vectors.py`, `poles/discover_poles.py` | ideology poles |
| `scripts/build_model_coverage.py` | `configs/model_coverage.json` |
| `scripts/package_public_models.py`, `scripts/publish_public_models.sh`, `scripts/rebuild_public_manifest.py` | public model release |
| `scripts/inventory_native_models.py`, `scripts/cleanup_native_lsm_models.py` | installed-model inventory / trimming |
| `scripts/audit_native_maps.py`, `scripts/audit_eurobarometer_assets.py` | model/map audits |
| `scripts/test_native_lsm_dtag.py`, `scripts/test_country_conditioning.py` | no-LLM runtime contract / country tests |
| `scripts/check_dtag_readiness.py`, `scripts/audit_clean_repo.py` | repository readiness (`dtag-doctor`) |
| `scripts/build_native_bindings.sh` | build the native runtime extension |

## Commands

| Command | Purpose |
|---|---|
| `dtag-web` / `webapp/run.sh` | browser workbench + HTTP API |
| `dtag-models` | download/verify public native models |
| `dtag-doctor` | readiness and clean-surface checks |
| `python -m optimizer ...` | question optimization |
| `python -m optimizer.one_step_geometry ...` | exact one-step item/response geometry |

## Archive

`archive/` holds the deprecated command-line runtime: `pipeline.py` (CLI `main()`),
`interactive.py`, `run.py`, `run_grid.py`, `post.py`, `postprocess.py`, `smoke_test.py`,
`benchmark_native_runtime.py`, the Eurobarometer CLI launcher, `bin/*.sh` and
`experiments/`. It is kept for reference only: not tested, not maintained, and not runnable in
place. See [`archive/README.md`](archive/README.md) for what moved and how to restore a file.

## Assumptions and limitations

DTAG currently assumes:

- native LSM models represent discrete/categorical survey state spaces;
- every model feature has a map row;
- user questions can be matched to relevant survey variables with sufficient semantic confidence;
- persona attributes are explicit state constraints only when compatible survey variables exist;
- survey-wave selection is discrete rather than continuous interpolation;
- geographic conditioning is constrained by fields present in the selected survey;
- native conditional predictions do not imply causal effects;
- generated language is an interpretation layer anchored to model distributions, not a literal response emitted by the LSM;
- semantic-union fallback documentation is weaker evidence than wave-specific documentation and remains explicitly marked.

DTAG generates a model-conditioned digital twin of survey-response behavior. It should not be interpreted as a literal individual, a causal simulator, or a deterministic forecast of a real person's future choices.

## Model distribution

The ≈6.6 GB native corpus stays outside Git. Release `v0.2.1` is published as one SHA256-checksummed
`.tar.zst` archive per model (≈0.94 GB in total) in the public bucket `git-zeroknowledgediscovery-dtag`.
It is read anonymously over HTTPS through
`https://storage.googleapis.com/git-zeroknowledgediscovery-dtag/models/v0.2.1/manifest.json`.
`dtag-models` and the web app download, verify, extract and validate models on demand into the model
root (`DTAG_MODEL_ROOT`, an already-populated `<repo>/models/lsm`, or `~/.cache/dtag/models`). See
[docs/MANUAL.md §6](docs/MANUAL.md#6-native-models-where-they-are-and-how-they-are-pulled-in).

Never commit long-lived cloud credentials or API keys.

## Current status

Validated native surface:

```text
35 GSS
9 Afrobarometer
1 WVS7 pooled
207 Eurobarometer
252 native models
252 semantic maps
full model-map overlap
```

The main remaining engineering work is continued semantic improvement of fallback documentation for a subset of Eurobarometer waves, and fieldwork dates for the 15 newest Eurobarometer waves (selectable by ZA number only).

## Name

**DTAG = Digital Twin Anchored Generation.**
