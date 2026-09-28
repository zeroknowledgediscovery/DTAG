# Native LSM DTAG development

This branch develops native C++ LSM support without changing the validated
legacy DTAG release on `main`.

## Development branch

```text
dev/native-lsm-dtag
```

Do not merge this branch to `main` until the native model/runtime validation
suite has passed.

## Model placement

Legacy Quasinet models stay where they are.

Native LSM models use a separate tree:

```text
models/lsm/
  gss/
    gss_2018/
    gss_2022/
    gss_2024/
  wvs/
    wvs7_pooled/
  afrobarometer/
    r1/
    ...
    r9/
  eurobarometer/
    ZAxxxx/
  anes/
  ces/
  ess/
  latinobarometro/
  arab_barometer/
```

A native model directory is expected to contain at least:

```text
source_maps/
trees/binary/
meta.txt
training_manifest.json
```

The DTAG runtime auto-detects a directory with `source_maps/` and
`trees/binary/` as a native LSM model.

## First validation set

The first native DTAG models are pooled GSS waves:

```text
gss_2018.csv -> models/lsm/gss/gss_2018
gss_2022.csv -> models/lsm/gss/gss_2022
gss_2024.csv -> models/lsm/gss/gss_2024
```

These names match the canonical GSS wave organization in the MAGICS survey
data tree.

Using pooled wave models is deliberate: persona sex, age, race, work status,
etc. are conditioned as model state rather than choosing a separate model by
sex. The old sex-specific 2022 Quasinet models remain available for A/B
comparison.

## Build native LSM and bindings

In the LSM repository:

```bash
cmake -S . -B build-bindings -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DENABLE_PROFILING=OFF \
  -DBUILD_PYTHON_BINDINGS=ON

cmake --build build-bindings \
  --target LSM predict_distribution qdistance qsample \
  -j "$(nproc)"
```

Then point DTAG at the executable/bindings:

```bash
export LSM_BIN=/path/to/lsm/bin/LSM
export LSM_BINDINGS_DIR=/path/to/lsm/bin
```

`LSM_BINDINGS_DIR` is used by `scripts/model_backend.py`; setting
`PYTHONPATH=/path/to/lsm/bin` is also supported.

## Train the three GSS examples

If a directory contains:

```text
gss_2018.csv
gss_2022.csv
gss_2024.csv
```

run:

```bash
python3 scripts/train_native_lsm_models.py /path/to/gss \
  --model gss_2018 \
  --model gss_2022 \
  --model gss_2024 \
  --lsm-bin "$LSM_BIN" \
  --threads 12
```

Equivalent convenience wrapper:

```bash
bash bin/train_native_gss_examples.sh /path/to/gss \
  --lsm-bin "$LSM_BIN" \
  --threads 12
```

The catalog is:

```text
configs/native_lsm_catalog.yaml
```

The training driver performs, in order:

1. read the source CSV;
2. deterministically sample rows when a sample size is requested;
3. identify/remove a respondent index column;
4. normalize missing values to empty strings;
5. remove columns that are all empty **after sampling**;
6. write a prepared training CSV under `outputs/native_lsm_training/`;
7. save the selected respondent IDs/row indices;
8. write `training_manifest.json`;
9. run native `LSM`;
10. place the final model directory under `models/lsm/`.

Prepare without training:

```bash
python3 scripts/train_native_lsm_models.py /path/to/gss \
  --model gss_2024 \
  --prepare-only
```

Print an LSM command without executing it:

```bash
python3 scripts/train_native_lsm_models.py /path/to/gss \
  --model gss_2024 \
  --dry-run
```

## Bulk survey-family training

For survey families with many wave CSVs, the same driver can discover the files
from the `planned_families` section of the catalog.

Eurobarometer example:

```bash
python3 scripts/train_native_lsm_models.py /path/to/eurobarometer \
  --family eurobarometer \
  --lsm-bin "$LSM_BIN" \
  --threads 120
```

This discovers `ZA*.csv` and writes one model per wave under:

```text
models/lsm/eurobarometer/<CSV-stem>/
```

The same pattern is reserved for ANES, CES, ESS, Latinobarómetro, and Arab
Barometer. Those families should be bulk-trained only after their canonical
prepared CSV and DTAG-map conventions are fixed.

## Runtime architecture

`scripts/model_backend.py` provides the compatibility layer.

Both backends expose:

```text
feature_names
possible_values()
predict_distributions(state, target_names=...)
qdistance(state_a, state_b)
```

Backends:

```text
QuasinetBackend
NativeLSMBackend
```

`scripts/pipeline.py` uses this interface rather than importing Quasinet
directly.

Legacy file:

```text
models/gss/gss_2024.gz
```

is automatically interpreted as Quasinet.

Native directory:

```text
models/lsm/gss/gss_2024/
```

is automatically interpreted as native LSM.

The command-line option can override detection:

```text
--model_backend auto
--model_backend quasinet
--model_backend native_lsm
```

## Native development profiles

Once the corresponding models have been trained:

```bash
bin/interactive_config.sh --list
```

includes development profiles such as:

```text
gss2018_native_wf
gss2018_native_cm
gss2022_native_wf
gss2022_native_cm
gss2024_native_wf
gss2024_native_cm
wvs7_native_india_2017
afrobarometer_r5_native_nigeria
afrobarometer_r5_native_ghana
```

Missing development models are shown as `[model not trained]`.

Example:

```bash
bin/interactive_config.sh \
  --profile gss2024_native_cm \
  --question "What do you think about immigration?"
```

Everything above the model backend remains the same DTAG pipeline: map
selection, persona assignment, geographic conditioning, state evolution,
semantic fallback, answer generation, logging, and ideology calculation.

## No-LLM native deployment test

After one or more models have been trained:

```bash
python3 scripts/test_native_lsm_dtag.py
```

This checks every native development model that exists and skips those not yet
trained.

For each available model it checks:

- model directory structure;
- source-map feature names;
- categorical support;
- one all-missing conditional prediction;
- probability normalization;
- self-qdistance;
- model/map overlap;
- Nigeria/Ghana categorical conditioning for native Afrobarometer R5.

Run one actual OpenAI-backed end-to-end question after the no-LLM tests pass:

```bash
python3 scripts/test_native_lsm_dtag.py \
  --run-openai \
  --profile gss2024_native_cm
```

## Next model sequence

After GSS 2018/2022/2024:

1. Afrobarometer R5 — validates categorical country conditioning.
2. WVS7 pooled — validates year and coordinate localization.
3. Afrobarometer R1-R9.
4. Eurobarometer — one native LSM per ZA wave.
5. ANES.
6. CES.
7. ESS.
8. Latinobarómetro.
9. Arab Barometer.

The catalog already reserves the model hierarchy for these survey families.
Individual wave entries should be added only when the canonical CSV and map
names are known.

## Merge gate

Do not replace the legacy DTAG profiles or remove `quasinet` until the
following have passed:

- Python/static checks;
- native model structure/readiness;
- model-map feature overlap;
- GSS one-question run;
- GSS multi-question stateful run;
- GSS ideology trajectory;
- Afrobarometer Nigeria/Ghana hard conditioning;
- WVS country/year localization;
- old-vs-native conditional-distribution comparison on common states;
- old-vs-native ideology comparison on common GSS states;
- deployment smoke with the intended binding packaging.

Only after those checks should native profiles become the default profiles.
