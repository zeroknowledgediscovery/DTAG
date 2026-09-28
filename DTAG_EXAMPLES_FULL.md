# DTAG examples

These examples describe the public `v0.1.0-rc1` interface. Commands assume the current directory is the DTAG repository root.

## 1. Installation and readiness

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export OPENAI_API_KEY="YOUR_KEY"

python3 scripts/check_dtag_readiness.py \
  --create-smoke-csv \
  --overlap
```

RC1 is expected to report zero failures. Eurobarometer may appear as a warning because it is intentionally outside the bundled RC1 runtime surface.

## 2. List available workflows

Interactive profiles:

```bash
bin/interactive_config.sh --list
```

Batch experiments:

```bash
bin/list_experiments.sh
```

## 3. GSS 2022

Progressive female:

```bash
bin/interactive_config.sh --profile gss2022_wf
```

Conservative male:

```bash
bin/interactive_config.sh --profile gss2022_cm
```

One question:

```bash
bin/interactive_config.sh \
  --profile gss2022_cm \
  --question "What do you think about immigration?"
```

GSS 2022 uses separate female/male LSMs and enables GSS polar-vector ideology tracking.

## 4. Pooled GSS 2024

Progressive female persona:

```bash
bin/interactive_config.sh --profile gss2024_wf
```

Conservative male persona:

```bash
bin/interactive_config.sh --profile gss2024_cm
```

Both use:

```text
models/gss/gss_2024.gz
maps/map2024.csv
```

The 2024 model is pooled; persona text initializes respondent state rather than selecting a sex-specific model.

## 5. WVS7 India 2017

```bash
bin/interactive_config.sh --profile wvs7_india_2017
```

One question:

```bash
bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --question "How satisfied are you with the way democracy works?"
```

The profile uses `models/wvs/LSM60K.gz` and `maps/wvs7_variable_question_map.csv`. Ideology is disabled by default.

## 6. Afrobarometer Nigeria versus Ghana

Terminal 1:

```bash
bin/interactive_config.sh --profile afrobarometer_r5_nigeria
```

Terminal 2:

```bash
bin/interactive_config.sh --profile afrobarometer_r5_ghana
```

Ask the same questions in both sessions:

```text
Do you trust the government?
How serious is corruption?
How satisfied are you with democracy?
What do you think about the economy?
```

The two profiles use the same R5 model/map but different hard-conditioned country states.

No-LLM regression test:

```bash
python3 scripts/test_country_conditioning.py
```

The validated R5 model should resolve through:

```text
COUNTRY_ALPHA
```

Full paired smoke test:

```bash
bin/smoke_country_pair.sh
```

## 7. Autoplay / question sequences

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv
```

The CSV should contain a `question` column. Questions are processed sequentially while respondent state persists.

## 8. Semantic fallback

Conservative RC1 behavior:

```bash
bin/interactive_config.sh \
  --profile gss2024_cm \
  --semantic_fallback answer_only \
  --question "What are your thoughts about the climate?"
```

For influence-propagation experiments:

```bash
bin/interactive_config.sh \
  --profile gss2024_cm \
  --semantic_fallback update_state
```

`update_state` is experimental.

## 9. Batch experiments

Run:

```bash
bin/run_config.sh gss2022_divergence
```

Equivalent:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_divergence
```

Dry-run:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_divergence \
  --dry-run
```

Postprocess:

```bash
bin/post_config.sh gss2022_divergence
```

## 10. Output artifacts

A run normally writes:

```text
*.log
*.meta.json
*.final_state.json
*.questions.csv
*.ideology.csv        # when ideology is enabled
```

The metadata records model/map paths, persona, geographic resolution, question records, semantic-fallback behavior, and final-state information.

## 11. Model/map pairs

```text
GSS 2022:
  models/gss/gss_2022female.pkl.gz
  models/gss/gss_2022male.pkl.gz
  maps/map2022.csv

GSS 2024:
  models/gss/gss_2024.gz
  maps/map2024.csv

WVS7:
  models/wvs/LSM60K.gz
  maps/wvs7_variable_question_map.csv

Afrobarometer R1-R5:
  models/afrobarometer/LSM_merged_rN_data.gz
  maps/afromap/afrobarometer_rN_map.csv
```

Run `check_dtag_readiness.py --overlap` whenever a model or map changes.

## 12. Rebuilding maps

Example GSS map generation:

```bash
python3 scripts/make_map.py \
  --dta data/raw/GSS2024.dta \
  --codebook_pdf data/raw/GSS_2024_Codebook.pdf \
  --out maps/map2024.csv
```

Example Afrobarometer map generation:

```bash
python3 scripts/getmap_dtag.py \
  --data /path/to/merged_r5_data.sav \
  --codebook_pdf /path/to/merged_r5_codebook.pdf \
  --qnet models/afrobarometer/LSM_merged_r5_data.gz \
  --out maps/afromap/afrobarometer_r5_map.csv
```

Raw source survey files/codebooks are intentionally not bundled.

## 13. Direct low-level execution

For development/debugging:

```bash
python3 scripts/pipeline_localized.py \
  --qnet models/afrobarometer/LSM_merged_r5_data.gz \
  --map maps/afromap/afrobarometer_r5_map.csv \
  --persona "35 year old urban male, regular news consumer, politically attentive, moderate" \
  --country Nigeria \
  --continent Africa \
  --assets_dir assets \
  --logs_dir outputs/manual_afro_r5_nigeria \
  --tag manual_afro_r5_nigeria \
  --semantic_fallback answer_only \
  --resp_mode max \
  --no_ideology \
  --question "Do you trust the government?"
```

For routine use, named profiles are preferred.

## 14. RC1 limitations

RC1 does not advertise:

- Afrobarometer R6-R9 trained models
- Eurobarometer runtime support
- automatic country/year-to-survey routing
- models regenerated with the newest manifest-based LSM training pipeline

Those are subsequent-release work, not requirements for this runnable release candidate.
