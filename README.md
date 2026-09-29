# DTAG — Digital Twin Anchored Generation

DTAG is a survey-grounded generative system built on native Large Science Models (LSMs). It conditions a learned survey-state model on a persona, time, and place where supported; maps natural-language questions to survey variables; predicts conditional response distributions; and uses those distributions to anchor generated answers.

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

## Quick start

DTAG can be installed directly from the public GitHub branch; no manual clone is required.

```bash
python3.13 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install \
  "git+https://github.com/zeroknowledgediscovery/DTAG.git@native-lsm-clean"
```

List the available DTAG profiles:

```bash
dtag --list
```

Install the model needed for a profile from the public DTAG model store. For example:

```bash
dtag-models gss/gss_2024
```

Models are downloaded once, SHA256-verified, decompressed into the local cache, and reused on later runs. The default cache is:

```text
~/.cache/dtag/models/
```

Set the OpenAI API key and start an interactive DTAG session:

```bash
export OPENAI_API_KEY="..."

dtag --profile gss2024_cm
```

A complete minimal setup is therefore:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@native-lsm-clean"

dtag-models gss/gss_2024

export OPENAI_API_KEY="..."
dtag --profile gss2024_cm
```

To inspect the public model catalog:

```bash
dtag-models --list
```

To install all models in one survey family:

```bash
dtag-models --family gss
```

To install the complete public model corpus:

```bash
dtag-models --all
```

On compatible CPython 3.13 x86-64 Linux systems, DTAG uses the bundled prebuilt native LSM extension. Other supported environments can rebuild the native extension from the source shipped with the installed repository tree.


## Architecture

DTAG separates three layers:

1. **Native LSM model** — learned conditional structure and state geometry.
2. **Semantic map** — model variable to survey question/label text.
3. **Generation layer** — maps a user question into survey variables, conditions the digital twin, predicts response distributions, and generates an answer anchored to those distributions.

A DTAG state is therefore a survey-variable state constrained by the native LSM, not merely free-form conversational history.

## Repository layout

```text
DTAG/
  assets/                       question sets, polar vectors, runtime caches
  bin/                          supported shell entry points
  configs/
    dtag_config.yaml            native model/map profiles and experiments
    eurodates.csv               Eurobarometer fieldwork-date registry
  data/                         local documentation/raw-data staging
  maps/
    gss/                        35 GSS per-wave maps
    afromap/                    Afrobarometer R1-R9 maps
    eurobarometer/              207 ZA-specific maps
    wvs7_variable_question_map.csv
  models/
    lsm/
      README.md                 tracked placeholder/documentation only
  scripts/                      runtime, builders, audits, tests
  outputs/                      generated run outputs; ignored by Git
  README.md
  requirements.txt
  VERSION
```

Native model binaries are intentionally **not stored in Git**. A complete local installation is currently about 6.6 GB.

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

When `DTAG_MODEL_ROOT` is unset, DTAG falls back to `<repo>/models/lsm`.

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

## First test / full demonstration

Run the repository-wide deterministic demo:

```bash
bin/dtag_demo.sh
```

Faster structural version:

```bash
bin/dtag_demo.sh --quick
```

Add live OpenAI-backed demonstrations:

```bash
bin/dtag_demo.sh --openai
```

Use a custom demonstration question:

```bash
bin/dtag_demo.sh   --openai   --question "Do you trust the national government?"
```

The demo covers native model inventory, syntax, backend contract tests, country conditioning, readiness, model/map audits, configured GSS/WVS/Afrobarometer profiles, Eurobarometer date/place routing, and optional live answer generation.

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

## Interactive profiles

List configured profiles:

```bash
bin/interactive_config.sh --list
```

Representative profiles:

```text
gss2018_wf
gss2018_cm
gss2022_wf
gss2022_cm
gss2024_wf
gss2024_cm
wvs7_india_2017
afrobarometer_r5_nigeria
afrobarometer_r5_ghana
```

Run interactively:

```bash
bin/interactive_config.sh --profile gss2024_cm
```

Run one question:

```bash
bin/interactive_config.sh   --profile gss2024_cm   --question "What do you think about immigration?"
```

Print the underlying runtime command:

```bash
bin/interactive_config.sh   --profile gss2024_cm   --question "What do you think about immigration?"   --print-command
```

## Canonical runtime

Core runtime:

```text
scripts/pipeline.py
```

Localized runtime:

```text
scripts/pipeline_localized.py
```

Config-driven launcher:

```text
scripts/interactive.py
```

Normal use should prefer `bin/interactive_config.sh` or `scripts/eurobarometer_native.py`.

A historical `--qnet` option spelling remains as a low-level compatibility alias, but on this branch it accepts only a **native LSM model directory**. There is no Quasinet backend.

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

1. direct categorical country variable;
2. WVS-style geographic proxy fields such as coordinates;
3. contextual localization if no deterministic survey variable exists.

Afrobarometer deterministic country conditioning can be tested with:

```bash
python3 scripts/test_country_conditioning.py
```

and end-to-end:

```bash
bin/smoke_country_pair.sh
```

### Time

Time handling is family-specific.

- **GSS:** model selection is wave-specific.
- **WVS7:** year may additionally be conditioned if the pooled model exposes a compatible field.
- **Eurobarometer:** a calendar date is routed to a fieldwork wave.

## Eurobarometer date + country

Example:

```bash
python3 scripts/eurobarometer_native.py   --date 2019-05-15   --country France   --question "How satisfied are you with the way democracy works?"
```

The fieldwork registry is:

```text
configs/eurodates.csv
```

An explicit ZA is also supported:

```bash
python3 scripts/eurobarometer_native.py   --za ZA7575   --country France   --question "How satisfied are you with the way democracy works?"
```

Without `--question`, the wrapper enters interactive mode.

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

## Batch experiments

Configured experiments live in:

```text
configs/dtag_config.yaml
```

List:

```bash
bin/list_experiments.sh
```

Run:

```bash
bin/run_config.sh --experiment gss2024_master
```

Postprocess:

```bash
bin/post_config.sh --experiment gss2024_master
```

The batch layer supports persona grids, question sets, order variants, stochastic replicates, semantic fallback, and optional ideology trajectories.

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

Configured default: `answer_only`.

- `off`: no semantic fallback when direct mapping fails.
- `answer_only`: fallback assists response grounding but does not change persistent state.
- `update_state`: inferred assignments may update persistent state; use deliberately.

## Stateful sequences

DTAG can preserve survey-state assignments across a question sequence. When state updates are enabled, an answer may alter subsequent native-LSM conditionals.

CSV/autoplay question sequences are supported for controlled experiments.

## OpenAI API smoke test

Test only the external generation API patterns:

```bash
bin/run_smoketest.sh
```

This checks plain generation and the strict structured-output call used in variable selection.

## Supported scripts

| Script | Purpose |
|---|---|
| `scripts/pipeline.py` | native LSM DTAG core |
| `scripts/pipeline_localized.py` | deterministic geographic conditioning |
| `scripts/interactive.py` | config-driven interactive launcher |
| `scripts/eurobarometer_native.py` | Eurobarometer date/ZA + country launcher |
| `scripts/model_backend.py` | native LSM runtime interface |
| `scripts/dtag_paths.py` | repository/external model-store resolution |
| `scripts/run.py` | configured batch launcher |
| `scripts/run_grid.py` | persona/question/order/replicate grid |
| `scripts/post.py` | configured postprocessing launcher |
| `scripts/postprocess.py` | postprocessing implementation |
| `scripts/check_dtag_readiness.py` | repository readiness |
| `scripts/inventory_native_models.py` | installed model inventory |
| `scripts/audit_native_maps.py` | 252-model map audit |
| `scripts/test_native_lsm_dtag.py` | no-LLM runtime contract test |
| `scripts/test_country_conditioning.py` | deterministic country test |
| `scripts/complete_native_maps.py` | all-family map completion |
| `scripts/build_all_gss_native_maps.py` | all-wave GSS maps |
| `scripts/getmap_dtag.py` | Afrobarometer map builder |
| `scripts/build_eurobarometer_maps.py` | exact Eurobarometer maps |
| `scripts/build_eurobarometer_fallback_maps.py` | semantic-union fallbacks |

Survey parsing/build scripts are development utilities, not alternate runtimes.

## Supported shell entry points

| Command | Purpose |
|---|---|
| `bin/dtag_demo.sh` | repository-wide deterministic/live demo |
| `bin/interactive_config.sh` | run/list profiles |
| `bin/run_config.sh` | run configured experiment |
| `bin/post_config.sh` | postprocess configured experiment |
| `bin/list_experiments.sh` | list configured experiments |
| `bin/smoke_country_pair.sh` | Nigeria/Ghana localization smoke |
| `bin/run_smoketest.sh` | OpenAI API smoke test |

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

The 6.6 GB native corpus should remain outside Git.

Recommended split:

```text
Git:
  source
  maps
  configs
  model manifest/checksums
  tests/demos

private object store:
  native LSM model artifacts
```

The intended distribution path is a private, versioned GCS model store. Trusted machines can use IAM/Application Default Credentials. A later download broker can issue short-lived signed URLs for users who should not receive bucket-level access.

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

The main remaining engineering work is model packaging/distribution and continued semantic improvement of fallback documentation for a subset of Eurobarometer waves.

## Name

**DTAG = Digital Twin Anchored Generation.**
