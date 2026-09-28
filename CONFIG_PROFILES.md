# Config-driven DTAG runs

This package now has two config-driven entry points:

```bash
python3 scripts/interactive.py --config configs/dtag_config.yaml --profile <profile> --loop
python3 scripts/run.py         --config configs/dtag_config.yaml --experiment <experiment>
```

Use `interactive.py` for manual question-by-question sessions, single questions, or a single autoplay CSV. Use `run.py` for batch experiments over all question sets, personas, order variants, and replicates.

## List available profiles and experiments

```bash
python3 scripts/interactive.py --config configs/dtag_config.yaml --list
python3 scripts/run.py --config configs/dtag_config.yaml --list
```

or via the wrapper:

```bash
bin/interactive_config.sh --list
bin/list_experiments.sh
```

## Interactive examples

Afrobarometer R5, Nigeria:

```bash
bin/interactive_config.sh --profile afrobarometer_r5_nigeria --loop
```

WVS7, Iran 2017:

```bash
bin/interactive_config.sh --profile wvs7_iran_2017 --loop
```

WVS7, India 2017:

```bash
bin/interactive_config.sh --profile wvs7_india_2017 --loop
```

GSS 2022, progressive white female persona, single question:

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --question "What do you think about immigration?"
```

Show the fully expanded command without running it:

```bash
bin/interactive_config.sh --profile wvs7_india_2017 --loop --print-command
```

## Batch examples

Afrobarometer R5 Nigeria over the master DTAG question set:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r5_nigeria_master_template
```

WVS7 Iran/India comparison over the master DTAG question set:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment wvs7_iran_india_master_template
```

GSS 2022 master comparison:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_master
```

## Where defaults live

Edit `configs/dtag_config.yaml`.

Global interactive defaults live under:

```yaml
defaults:
  interactive:
    k: 6
    resp_mode: max
    semantic_fallback: answer_only
    no_ideology: true  # set per profile, not globally, when needed
```

Batch defaults live under:

```yaml
defaults:
  run:
    runs_per_condition: 6
    variants: forward,reverse,shuffle
    resp_mode: draw
```

Interactive profiles live under:

```yaml
interactive_profiles:
  wvs7_india_2017:
    qnet: wvs7_lsm60k
    map: wvs7
    country: India
    year: 2017
```

Batch experiments live under:

```yaml
experiments:
  wvs7_iran_india_master_template:
    map: wvs7
    question_set: master
    personas:
      - id: WVS7_Iran_2017_UM
```

## Survey map rule

Use one map per model/wave:

```text
maps/afromap/afrobarometer_r1_map.csv
maps/afromap/afrobarometer_r2_map.csv
...
maps/afromap/afrobarometer_r9_map.csv
```

For WVS use `maps/wvs7_variable_question_map.csv`. For GSS 2022 use `maps/map2022.csv`.

## Ideology/polar-vector rule

GSS profiles can use `assets/polar_vectors/polar_vectors.csv` and set `require_polar_vectors: true`.

WVS and Afrobarometer profiles should normally set:

```yaml
polar_vectors: ""
run:
  no_ideology: true
```

until survey-specific polar vectors are created.

## Country conditioning behavior

WVS-style pooled models are hard-conditioned through `A_YEAR`, `O1_LONGITUDE`, and `O2_LATITUDE` when those features exist.

Afrobarometer-style models are hard-conditioned through direct country fields when available, in this order:

```text
COUNTRY_ALPHA
COUNTRY
country
COUNTRY.BY.REGION.NO
COUNTRY.BY.REGION
```

For example, the Round 5 qnet includes `COUNTRY_ALPHA`, `COUNTRY.BY.REGION.NO`, and `COUNTRY.BY.REGION`, so `country: Nigeria` is forced as part of the initial respondent state. The run metadata records these values under `forced_country_variables`.
