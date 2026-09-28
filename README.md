# DTAG

**DTAG (Digital Twin Attitude Generator)** is a survey-grounded synthetic respondent and synthetic survey simulator built on Large Science Models (LSMs/qnets).

This repository is a **research release candidate: v0.1.0-rc1**. It freezes the currently functioning runtime while survey models are progressively regenerated with the latest standardized LSM training pipeline.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OPENAI_API_KEY="YOUR_KEY"

python3 scripts/check_dtag_readiness.py \
  --create-smoke-csv \
  --overlap

bin/interactive_config.sh --list
```

Interactive GSS 2024 conservative-male respondent:

```bash
bin/interactive_config.sh --profile gss2024_cm
```

Afrobarometer Nigeria:

```bash
bin/interactive_config.sh --profile afrobarometer_r5_nigeria
```

WVS India 2017:

```bash
bin/interactive_config.sh --profile wvs7_india_2017
```

## Supported RC1 surface

| Survey family | RC1 status | Notes |
|---|---|---|
| GSS 2022 | Supported | Female/male LSMs; GSS polar-vector ideology tracking |
| GSS 2024 | Supported | Pooled LSM; 2024 map; persona-conditioned |
| WVS7 | Supported | Pooled `LSM60K.gz`; country/year conditioning; ideology disabled by default |
| Afrobarometer R1-R5 | Models/maps included | R5 Nigeria/Ghana deterministic country localization tested |
| Afrobarometer R6-R9 | Not included as trained models in RC1 | To be regenerated with the latest LSM training pipeline |
| Eurobarometer | Not included in RC1 | Planned for a subsequent release candidate |

## Interactive profiles

```bash
bin/interactive_config.sh --list
```

Expected RC profiles:

```text
gss2022_wf
gss2022_cm
gss2024_wf
gss2024_cm
wvs7_india_2017
afrobarometer_r5_nigeria
afrobarometer_r5_ghana
```

Run one question:

```bash
bin/interactive_config.sh \
  --profile gss2022_cm \
  --question "What do you think about immigration?"
```

## Canonical runtime

The canonical RC entry point is:

```text
scripts/pipeline_localized.py
```

It wraps `pipeline.py` and adds deterministic geographic conditioning.

Available modes:

```text
single question
interactive loop
CSV/autoplay question sequence
```

The default semantic fallback mode is `answer_only`. `update_state` is available as an experimental influence-propagation mode.

## Geographic conditioning

DTAG attempts location conditioning in this order:

1. direct categorical country feature when available;
2. WVS-style longitude/latitude proxy conditioning when supported;
3. context-only localization with a warning otherwise.

Afrobarometer R5 Nigeria/Ghana deterministic conditioning can be tested with:

```bash
python3 scripts/test_country_conditioning.py
bin/smoke_country_pair.sh
```

## Readiness

```bash
python3 scripts/check_dtag_readiness.py \
  --create-smoke-csv \
  --overlap
```

## Models and provenance

RC1 ships only model artifacts used by the currently validated DTAG workflows. Raw/merged survey datasets are not part of the public release tree.

The survey models in RC1 predate the newest manifest-based LSM training pipeline. Future release candidates will progressively replace them with models regenerated through that workflow while preserving the DTAG runtime interface.

## Research status

DTAG is research software. This release candidate is intended to make the current simulator reproducible and usable outside the development group while model coverage, validation, automatic survey routing, and additional survey families continue to expand.


## More documentation

- [Configuration profiles](CONFIG_PROFILES.md)
- [Complete runnable examples](DTAG_EXAMPLES_FULL.md)
- [RC1 scope](docs/RC1_SCOPE.md)
