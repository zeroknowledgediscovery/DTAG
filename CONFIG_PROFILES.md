# DTAG configuration profiles

DTAG's release-candidate interface is config-driven. The canonical configuration is:

```text
configs/dtag_config.yaml
```

For normal interactive use, prefer the profile launcher instead of writing a full `pipeline_localized.py` command.

## List available profiles

```bash
bin/interactive_config.sh --list
```

RC1 exposes:

```text
gss2022_wf
gss2022_cm
gss2024_wf
gss2024_cm
wvs7_india_2017
afrobarometer_r5_nigeria
afrobarometer_r5_ghana
```

## Interactive sessions

If neither `--question` nor `--autoplay_csv` is supplied, the launcher enters a persistent loop automatically:

```bash
bin/interactive_config.sh --profile gss2024_cm
```

Type one question per line. Type `exit` or `quit` to stop.

One question:

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --question "What do you think about immigration?"
```

Autoplay:

```bash
bin/interactive_config.sh \
  --profile afrobarometer_r5_nigeria \
  --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv
```

Print the expanded command without running it:

```bash
bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --print-command
```

## Profile overrides

A profile supplies its model, map, persona, geography, outputs, and run defaults. For one-off experiments you can override the persona, country, continent, year, output path/tag, or semantic fallback mode.

Example:

```bash
bin/interactive_config.sh \
  --profile gss2024_cm \
  --persona "55 year old male, suburban, college educated, conservative" \
  --question "What do you think about immigration?"
```

Semantic fallback choices are:

```text
off
answer_only
update_state
```

`answer_only` is the RC1 default. It can use broader semantic anchors without modifying respondent state. `update_state` is experimental.

## GSS

GSS 2022 uses separate sex-specific LSMs:

```text
gss2022_wf -> models/gss/gss_2022female.pkl.gz
gss2022_cm -> models/gss/gss_2022male.pkl.gz
```

GSS 2024 currently uses one pooled LSM for both standard personas:

```text
gss2024_wf -> models/gss/gss_2024.gz
gss2024_cm -> models/gss/gss_2024.gz
```

Both families use survey-specific maps, and GSS profiles enable the bundled polar vectors for ideology tracking when compatible.

## WVS7

`wvs7_india_2017` uses:

```text
models/wvs/LSM60K.gz
maps/wvs7_variable_question_map.csv
```

with year/country context:

```text
year      = 2017
country   = India
continent = Asia
```

When the pooled model exposes `A_YEAR`, `O1_LONGITUDE`, and `O2_LATITUDE`, DTAG uses them for hard year/location conditioning. Ideology is disabled by default.

## Afrobarometer

Both RC1 Afrobarometer demos use Round 5:

```text
models/afrobarometer/LSM_merged_r5_data.gz
maps/afromap/afrobarometer_r5_map.csv
```

The Nigeria and Ghana profiles are otherwise matched. The localized pipeline first looks for a categorical country variable; the validated R5 model resolves country through `COUNTRY_ALPHA`.

Regression test:

```bash
python3 scripts/test_country_conditioning.py
```

End-to-end paired smoke test:

```bash
bin/smoke_country_pair.sh
```

## Batch experiments

List configured experiments:

```bash
bin/list_experiments.sh
```

Current RC1 experiments include:

```text
gss2022_divergence
gss2022_original
gss2022_master
gss2024_divergence_template
gss2024_master_template
wvs7_us_india_master_template
```

Run one:

```bash
bin/run_config.sh gss2022_divergence
```

Dry-run:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_divergence \
  --dry-run
```

## Canonical runtime

The RC1 configuration points to:

```text
scripts/pipeline_localized.py
```

This wraps the core `pipeline.py` engine and adds deterministic geographic conditioning.

## RC1 scope

RC1 advertises the currently available trained models only:

- GSS 2022
- pooled GSS 2024
- pooled WVS7
- Afrobarometer R1-R5

Afrobarometer R6-R9 and Eurobarometer are not part of the supported RC1 runtime surface. See `docs/RC1_SCOPE.md`.
