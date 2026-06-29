# DTAG Examples: Config-Driven Interactive and Batch Runs

This file gives concrete examples for running DTAG across GSS, WVS, and Afrobarometer using the config-driven repository layout.

The intended workflow is:

```text
data/     raw survey files and codebooks, only needed for rebuilding maps/specs/models
models/   trained qnet/LSM model files
maps/     DTAG-ready variable -> question_text maps
assets/   question sets, polar vectors, country specs, cache files
outputs/  run logs, records, trajectories, plots
configs/  YAML configuration
scripts/  pipeline and runners
bin/      small wrapper scripts
```

The low-level engine is `scripts/pipeline.py`. For normal use, prefer named profiles and experiments in `configs/dtag_config.yaml`.

---

## 1. One-time setup

```bash
# Clone the repo
git clone https://github.com/zeroknowledgediscovery/DTAG.git
cd DTAG

# Create environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set OpenAI key
export OPENAI_API_KEY="YOUR_KEY_HERE"
```

Smoke test:

```bash
python3 scripts/smoke_test.py gpt-4.1-mini
```

Validate the YAML config:

```bash
python3 - <<'PY'
import yaml
from pathlib import Path

p = Path("configs/dtag_config.yaml")
with p.open() as f:
    cfg = yaml.safe_load(f)

print("Top-level keys:", list(cfg.keys()))
print("Models:", list(cfg.get("models", {}).keys()))
print("Maps:", list(cfg.get("maps", {}).keys()))
print("Question sets:", list(cfg.get("question_sets", {}).keys()))
print("Interactive profiles:", list(cfg.get("interactive_profiles", {}).keys()))
print("Experiments:", list(cfg.get("experiments", {}).keys()))
PY
```

---

## 2. What belongs where

### data/

Raw files only. These are not normally used at runtime unless rebuilding maps or country specs.

```text
data/
  gss/
    GSS2022.dta
    GSS2022_codebook.pdf
  wvs/
    wvs7_data.sav
    wvs7_codebook.pdf
  afrobarometer/
    merged_r1_data.sav
    merged_r1_codebook2.pdf
    merged_r2_data.sav
    merged_r2_codebook2.pdf
    ...
    merged_r9_data.sav
    merged_r9_codebook.pdf
```

### models/

Trained qnet/LSM model files.

```text
models/
  gss/
    gss_2022female.pkl.gz
    gss_2022male.pkl.gz
    gss_2024female.pkl.gz
    gss_2024male.pkl.gz
  wvs/
    LSM60K.gz
  afrobarometer/
    LSM_merged_r1_data.gz
    LSM_merged_r2_data.gz
    ...
    LSM_merged_r5_data.gz
```

### maps/

DTAG-ready variable-to-question maps. Each map must have:

```csv
variable,question_text
```

Recommended structure:

```text
maps/
  map2022.csv
  wvs7_variable_question_map.csv
  afromap/
    afrobarometer_r1_map.csv
    afrobarometer_r2_map.csv
    afrobarometer_r3_map.csv
    afrobarometer_r4_map.csv
    afrobarometer_r5_map.csv
    afrobarometer_r6_map.csv
    afrobarometer_r7_map.csv
    afrobarometer_r8_map.csv
    afrobarometer_r9_map.csv
```

### assets/

Runtime helper assets.

```text
assets/
  question_sets/
    master/*.csv
    original/*.csv
    divergence/*.csv
  polar_vectors/
    polar_vectors.csv
    polar_vectors_template.csv
  label_maps/
    question_set_interpretive_name_map_master.csv
    question_set_master_rename_manifest.csv
  country_specs/
    afrobarometer/
      merged_r1_country_specs.json
      merged_r2_country_specs.json
      ...
      merged_r9_country_specs.json
```

The `*.possible.<hash>.json` files under `assets/` are automatically generated qnet support caches. They are safe to delete; they will be regenerated.

---

## 3. Config file structure

The main config file is:

```text
configs/dtag_config.yaml
```

It should define:

```yaml
models:
  gss_2022_female: models/gss/gss_2022female.pkl.gz
  gss_2022_male: models/gss/gss_2022male.pkl.gz
  wvs7_lsm60k: models/wvs/LSM60K.gz
  afrobarometer_r5: models/afrobarometer/LSM_merged_r5_data.gz

maps:
  gss_2022: maps/map2022.csv
  wvs7: maps/wvs7_variable_question_map.csv
  afrobarometer_r5: maps/afromap/afrobarometer_r5_map.csv

question_sets:
  master:
    dir: assets/question_sets/master
    glob: "*.csv"

interactive_profiles:
  gss2022_wf:
    qnet: gss_2022_female
    map: gss_2022
    persona: "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive"
    logs_dir: outputs/interactive_WF
    tag: WF_interactive
    year: 2022
    country: United States
    polar_vectors: assets/polar_vectors/polar_vectors.csv
    run:
      no_ideology: false
      require_polar_vectors: true
      resp_mode: max
```

The important rule is that `qnet:` and `map:` inside a profile refer to keys in the top-level `models:` and `maps:` sections, not literal file paths unless your runner explicitly allows direct paths.

---

## 4. Listing profiles and experiments

List interactive profiles:

```bash
bin/interactive_config.sh --list
```

Equivalent direct command:

```bash
python3 scripts/interactive.py \
  --config configs/dtag_config.yaml \
  --list
```

List batch experiments:

```bash
bin/list_experiments.sh
```

Equivalent direct command:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --list
```

Show the fully expanded command without running:

```bash
bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --loop \
  --print-command
```

---

## 5. Interactive runs

Interactive mode means you start the session, then type one question at a time. Type `exit` or `quit` to stop.

### GSS 2022, progressive white female persona, manual loop

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --loop
```

### GSS 2022, conservative male persona, manual loop

```bash
bin/interactive_config.sh \
  --profile gss2022_cm \
  --loop
```

### GSS 2022, one question

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --question "What do you think about immigration?"
```

### WVS7, India 2017, manual loop

```bash
bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --loop
```

### WVS7, Iran 2017, manual loop

```bash
bin/interactive_config.sh \
  --profile wvs7_iran_2017 \
  --loop
```

### Afrobarometer R5, Nigeria, manual loop

```bash
bin/interactive_config.sh \
  --profile afrobarometer_r5_nigeria \
  --loop
```

---

## 6. Autoplay with a question-set CSV

Autoplay mode runs one CSV of questions through the profile.

Example with GSS:

```bash
bin/interactive_config.sh \
  --profile gss2022_wf \
  --autoplay_csv assets/question_sets/master/01_empirical_right_shift_compact_money_immigration_corruption_tax.csv
```

Example with WVS:

```bash
bin/interactive_config.sh \
  --profile wvs7_india_2017 \
  --autoplay_csv assets/question_sets/master/01_empirical_right_shift_compact_money_immigration_corruption_tax.csv
```

Example with Afrobarometer:

```bash
bin/interactive_config.sh \
  --profile afrobarometer_r5_nigeria \
  --autoplay_csv assets/question_sets/master/01_empirical_right_shift_compact_money_immigration_corruption_tax.csv
```

The CSV should have a column called `question`. If it does not, the pipeline generally uses the first column as the question text.

---

## 7. Batch experiments

Batch mode uses `scripts/run.py`. It is for running all question-set CSVs in a configured folder, across one or more personas, variants, and replicates.

### GSS 2022 master experiment

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_master
```

Postprocess:

```bash
python3 scripts/post.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_master
```

### WVS7 Iran/India comparison

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment wvs7_iran_india_master_template
```

### Afrobarometer R5 Nigeria master experiment

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r5_nigeria_master_template
```

### Dry-run batch command expansion

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r5_nigeria_master_template \
  --dry-run
```

or, depending on your runner version:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r5_nigeria_master_template \
  --print-command
```

---

## 8. Low-level direct pipeline commands

Use these only for debugging or when testing a new profile before adding it to YAML.

### Afrobarometer R5 Nigeria

```bash
python3 scripts/pipeline.py \
  --map maps/afromap/afrobarometer_r5_map.csv \
  --qnet models/afrobarometer/LSM_merged_r5_data.gz \
  --persona "35 year old urban male in Nigeria, regular news consumer, politically attentive, moderate" \
  --assets_dir assets \
  --logs_dir outputs/afrobarometer_r5_Nigeria_interactive \
  --tag Afrobarometer_R5_Nigeria_interactive \
  --country "Nigeria" \
  --continent "Africa" \
  --state_keep 500 \
  --k 6 \
  --prefilter 200 \
  --min_map_score 1.0 \
  --semantic_fallback answer_only \
  --semantic_k 6 \
  --semantic_prefilter 80 \
  --semantic_min_confidence 0.35 \
  --semantic_resp_mode max \
  --max_assign 50 \
  --assign_prefilter 500 \
  --resp_mode max \
  --seed 1000 \
  --timing \
  --no_ideology \
  --loop
```

### WVS7 India 2017

```bash
python3 scripts/pipeline.py \
  --map maps/wvs7_variable_question_map.csv \
  --qnet models/wvs/LSM60K.gz \
  --persona "35 year old male, urban, college educated, regular news consumer, politically moderate" \
  --assets_dir assets \
  --logs_dir outputs/interactive_wvs7_India_2017 \
  --tag WVS7_India_2017_interactive \
  --year 2017 \
  --country "India" \
  --continent "Asia" \
  --state_keep 500 \
  --k 6 \
  --prefilter 200 \
  --min_map_score 1.0 \
  --semantic_fallback answer_only \
  --semantic_k 6 \
  --semantic_prefilter 80 \
  --semantic_min_confidence 0.35 \
  --semantic_resp_mode max \
  --max_assign 50 \
  --assign_prefilter 500 \
  --resp_mode max \
  --seed 1000 \
  --timing \
  --no_ideology \
  --loop
```

### WVS7 Iran 2017

```bash
python3 scripts/pipeline.py \
  --map maps/wvs7_variable_question_map.csv \
  --qnet models/wvs/LSM60K.gz \
  --persona "35 year old male, urban, college educated, regular news consumer, politically moderate" \
  --assets_dir assets \
  --logs_dir outputs/interactive_wvs7_Iran_2017 \
  --tag WVS7_Iran_2017_interactive \
  --year 2017 \
  --country "Iran" \
  --continent "Asia" \
  --state_keep 500 \
  --k 6 \
  --prefilter 200 \
  --min_map_score 1.0 \
  --semantic_fallback answer_only \
  --semantic_k 6 \
  --semantic_prefilter 80 \
  --semantic_min_confidence 0.35 \
  --semantic_resp_mode max \
  --max_assign 50 \
  --assign_prefilter 500 \
  --resp_mode max \
  --seed 1000 \
  --timing \
  --no_ideology \
  --loop
```

### GSS 2022 with ideology tracking

```bash
python3 scripts/pipeline.py \
  --qnet models/gss/gss_2022female.pkl.gz \
  --map maps/map2022.csv \
  --persona "22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive" \
  --polar_vectors assets/polar_vectors/polar_vectors.csv \
  --assets_dir assets \
  --logs_dir outputs/interactive_WF \
  --tag WF_interactive \
  --year 2022 \
  --country "United States" \
  --semantic_fallback answer_only \
  --resp_mode max \
  --timing \
  --question "What do you think about immigration?"
```

---

## 9. When survey name matters

You do not normally pass `--survey GSS`, `--survey WVS`, or `--survey Afrobarometer` to `pipeline.py`.

The survey is determined by the model and map selected:

```text
GSS 2022:
  qnet = models/gss/gss_2022female.pkl.gz
  map  = maps/map2022.csv

WVS7:
  qnet = models/wvs/LSM60K.gz
  map  = maps/wvs7_variable_question_map.csv

Afrobarometer R5:
  qnet = models/afrobarometer/LSM_merged_r5_data.gz
  map  = maps/afromap/afrobarometer_r5_map.csv
```

Use survey names in config keys and file names for clarity:

```yaml
models:
  afrobarometer_r5: models/afrobarometer/LSM_merged_r5_data.gz
maps:
  afrobarometer_r5: maps/afromap/afrobarometer_r5_map.csv
interactive_profiles:
  afrobarometer_r5_nigeria:
    qnet: afrobarometer_r5
    map: afrobarometer_r5
```

---

## 10. Country and year conditioning

### GSS

GSS is US-only. Year and sex are usually encoded by the selected qnet file.

```text
gss_2022female.pkl.gz = GSS 2022 female model
gss_2022male.pkl.gz   = GSS 2022 male model
```

`year: 2022` and `country: United States` are still useful for metadata and prompt context, but usually do not hard-condition the qnet unless the model has explicit year/country variables.

### WVS

WVS pooled models may include:

```text
A_YEAR
O1_LONGITUDE
O2_LATITUDE
```

If those variables exist, `--year`, `--country`, and `--continent` can hard-condition the state.

Check support:

```bash
python3 - <<'PY'
from quasinet.qnet import load_qnet

m = load_qnet("models/wvs/LSM60K.gz")
features = set(m.feature_names)
for v in ["A_YEAR", "O1_LONGITUDE", "O2_LATITUDE", "B_COUNTRY", "B_COUNTRY_ALPHA"]:
    print(v, v in features)
PY
```

### Afrobarometer

Afrobarometer models usually have wave-specific qnets and direct country variables. Depending on the wave/model, country may be encoded as:

```text
COUNTRY_ALPHA
COUNTRY
country
COUNTRY.BY.REGION.NO
COUNTRY.BY.REGION
```

The pipeline attempts hard country conditioning through these direct fields when available. The run metadata should record the forced country variables.

Inspect country fields:

```bash
python3 - <<'PY'
from quasinet.qnet import load_qnet

m = load_qnet("models/afrobarometer/LSM_merged_r5_data.gz")
for v in m.feature_names:
    if "COUNTRY" in v.upper() or v.lower() == "country":
        print(v)
PY
```

---

## 11. Polar vectors and ideology tracking

Polar vectors are only needed for ideology/drift trajectories. They are not needed for ordinary question answering.

### Use polar vectors for GSS

GSS profile:

```yaml
gss2022_wf:
  polar_vectors: assets/polar_vectors/polar_vectors.csv
  run:
    no_ideology: false
    require_polar_vectors: true
```

Direct command pattern:

```bash
python3 scripts/pipeline.py \
  --qnet models/gss/gss_2022female.pkl.gz \
  --map maps/map2022.csv \
  --polar_vectors assets/polar_vectors/polar_vectors.csv \
  --require_polar_vectors \
  --question "What do you think about immigration?"
```

### Disable ideology for WVS/Afrobarometer by default

WVS and Afrobarometer should normally use:

```yaml
polar_vectors: ""
run:
  no_ideology: true
```

Direct command:

```bash
--no_ideology
```

Do not reuse GSS polar vectors for WVS or Afrobarometer unless the variable names and response labels exactly match the qnet support. Usually they will not.

### Creating survey-specific polar vectors

A polar vector file should look like:

```csv
variable,left,right
Q38,Statement B: Sometimes non-democratic preferable,Statement A: Democracy preferable
Q40,Not at All Satisfied,Very Satisfied
```

The exact response strings must match the model’s possible responses.

Inspect allowed responses:

```bash
python3 - <<'PY'
from quasinet.qnet import load_qnet
import numpy as np

qnet_path = "models/afrobarometer/LSM_merged_r5_data.gz"
vars_to_check = ["Q38", "Q40"]

m = load_qnet(qnet_path)
x = np.array([""] * len(m.feature_names)).astype("U100")
dists = m.predict_distributions(x)
idx = {v: i for i, v in enumerate(m.feature_names)}

for v in vars_to_check:
    print("\n", v)
    if v not in idx:
        print("not in model")
        continue
    print(list(dists[idx[v]].keys()))
PY
```

---

## 12. Semantic fallback and no-match behavior

The current pipeline has three relevant mapping behaviors:

```text
direct mapping      strong survey-variable match; state can update
semantic fallback   indirect but defensible match; default answer-only, no state update
no match            no defensible anchor; no answer and no state update
```

Recommended defaults:

```yaml
semantic_fallback: answer_only
semantic_k: 6
semantic_prefilter: 80
semantic_min_confidence: 0.35
semantic_resp_mode: max
min_map_score: 1.0
```

Direct command flags:

```bash
--semantic_fallback answer_only \
--semantic_k 6 \
--semantic_prefilter 80 \
--semantic_min_confidence 0.35 \
--semantic_resp_mode max \
--min_map_score 1.0
```

Use `answer_only` as the default. It allows broad semantic answers, but prevents weak indirect anchors from contaminating the digital-twin trajectory.

Use `update_state` only for deliberate experiments:

```bash
--semantic_fallback update_state
```

Use `off` for strict ablation:

```bash
--semantic_fallback off
```

---

## 13. Map generation

Use one map per survey wave/model.

Do not use one giant Afrobarometer map unless you also create one harmonized all-wave qnet.

### Afrobarometer R5 map

```bash
python3 scripts/getmap_dtag.py \
  --data data/afrobarometer/merged_r5_data.sav \
  --codebook_pdf data/afrobarometer/merged_r5_codebook.pdf \
  --qnet models/afrobarometer/LSM_merged_r5_data.gz \
  --out maps/afromap/afrobarometer_r5_map.csv \
  --text-mode combined
```

### Afrobarometer R9 map

```bash
python3 scripts/getmap_dtag.py \
  --data data/afrobarometer/merged_r9_data.sav \
  --codebook_pdf data/afrobarometer/merged_r9_codebook.pdf \
  --qnet models/afrobarometer/LSM_merged_r9_data.gz \
  --out maps/afromap/afrobarometer_r9_map.csv \
  --text-mode combined
```

### GSS 2024 map

```bash
python3 scripts/make_map.py \
  --dta data/gss/GSS2024.dta \
  --codebook_pdf data/gss/GSS_2024_Codebook.pdf \
  --out maps/map2024.csv
```

Then add to config:

```yaml
maps:
  gss_2024: maps/map2024.csv
```

---

## 14. Country specs for Afrobarometer

Country specs are useful for auditing and hard country conditioning.

```bash
python3 scripts/build_country_specs.py \
  --data data/afrobarometer/merged_r5_data.sav \
  --codebook_pdf data/afrobarometer/merged_r5_codebook.pdf \
  --out_json assets/country_specs/afrobarometer/merged_r5_country_specs.json \
  --out_csv assets/country_specs/afrobarometer/merged_r5_country_specs.csv
```

Keep one country-spec file per wave:

```text
assets/country_specs/afrobarometer/merged_r1_country_specs.json
assets/country_specs/afrobarometer/merged_r2_country_specs.json
...
assets/country_specs/afrobarometer/merged_r9_country_specs.json
```

---

## 15. Map/qnet intersection check

Before running a new survey or wave, always check that the map variables intersect the qnet feature names.

```bash
python3 - <<'PY'
import pandas as pd
from quasinet.qnet import load_qnet

map_path = "maps/afromap/afrobarometer_r5_map.csv"
qnet_path = "models/afrobarometer/LSM_merged_r5_data.gz"

m = load_qnet(qnet_path)
df = pd.read_csv(map_path, dtype=str)

map_vars = set(df["variable"].dropna().astype(str))
qnet_vars = set(m.feature_names)
inter = map_vars & qnet_vars

print("map variables:", len(map_vars))
print("qnet variables:", len(qnet_vars))
print("intersection:", len(inter))
print("intersection fraction:", len(inter) / max(1, len(map_vars)))
print("map-only examples:", sorted(list(map_vars - qnet_vars))[:30])
print("qnet-only examples:", sorted(list(qnet_vars - map_vars))[:30])
PY
```

If intersection is low, the map and model variable naming do not match. Regenerate the map with `--qnet`, or normalize variable names consistently.

---

## 16. Adding a new interactive profile

Example: Afrobarometer R7 Kenya.

First add model and map keys:

```yaml
models:
  afrobarometer_r7: models/afrobarometer/LSM_merged_r7_data.gz

maps:
  afrobarometer_r7: maps/afromap/afrobarometer_r7_map.csv
```

Then add profile:

```yaml
interactive_profiles:
  afrobarometer_r7_kenya:
    description: Afrobarometer Round 7, Kenya persona, interactive loop; ideology disabled by default.
    qnet: afrobarometer_r7
    map: afrobarometer_r7
    persona: "35 year old urban male in Kenya, regular news consumer, politically attentive, moderate"
    logs_dir: outputs/afrobarometer_r7_Kenya_interactive
    tag: Afrobarometer_R7_Kenya_interactive
    country: Kenya
    continent: Africa
    polar_vectors: ""
    run:
      no_ideology: true
      resp_mode: max
```

Run:

```bash
bin/interactive_config.sh --profile afrobarometer_r7_kenya --loop
```

---

## 17. Adding a new batch experiment

Example: Afrobarometer R7 Kenya over the master question set.

```yaml
experiments:
  afrobarometer_r7_kenya_master:
    description: Afrobarometer R7 Kenya persona on the master question set; ideology disabled.
    map: afrobarometer_r7
    question_set: master
    outdir: outputs/dtag_afrobarometer_r7_kenya_master
    polar_vectors: ""
    run:
      no_ideology: true
      resp_mode: max
      semantic_fallback: answer_only
      runs_per_condition: 3
      parallel: 3
      variants: forward
      k: 6
    personas:
      - id: Afro_R7_Kenya_UM
        qnet: afrobarometer_r7
        persona: "35 year old urban male in Kenya, regular news consumer, politically attentive, moderate"
        country: Kenya
        continent: Africa
```

Run:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r7_kenya_master
```

---

## 18. Output files to inspect

After a run, inspect the output directory specified by `logs_dir` or `outdir`.

Typical files:

```text
*.log                full console log
*.meta.json          run metadata, paths, settings, country/year forcing
*.records.json       question-by-question records
*.final_state.json   final respondent state
*.ideology.csv       ideology trajectory, only if ideology enabled
```

For semantic fallback diagnostics, inspect `*.records.json` fields such as:

```json
{
  "direct_mapping": false,
  "semantic_fallback": true,
  "semantic_state_updated": false,
  "skip_reason": null
}
```

For no-match cases:

```json
{
  "skipped": true,
  "skip_reason": "no_relevant_survey_variable"
}
```

For country conditioning diagnostics, inspect `*.meta.json` fields such as:

```json
{
  "forced_assignments": {
    "COUNTRY_ALPHA": "NIG"
  },
  "forced_country_variables": {
    "COUNTRY_ALPHA": "NIG"
  }
}
```

---

## 19. Recommended CSS2026 runs

Use three survey families:

### 1. GSS as ideology/drift demonstration

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_master
```

This produces the clearest ideology trajectory because GSS polar vectors are available.

### 2. WVS as cross-national pooled-model demonstration

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment wvs7_iran_india_master_template
```

This demonstrates country/year conditioning and cross-national differences.

### 3. Afrobarometer as external survey-family transfer

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment afrobarometer_r5_nigeria_master_template
```

This demonstrates that DTAG is not GSS-specific and can operate on a different comparative political survey family.

Suggested paper figures:

```text
Figure 1: DTAG architecture
Prompt -> mapper -> qnet state -> anchored response -> trajectory/records

Figure 2: GSS ideology trajectory
WF vs CM under master question sets

Figure 3: Cross-survey prompt grounding
GSS vs WVS vs Afrobarometer direct-map, semantic-fallback, no-match rates

Figure 4: Country-conditioned contrast
WVS Iran vs India or Afrobarometer Nigeria vs another country

Figure 5: Failure-mode control
No-match and answer-only fallback prevent state contamination
```

Suggested tables:

```text
Table 1: Survey assets and model coverage
Survey, wave/year, qnet file, map file, variables, countries, country/year conditioning

Table 2: Prompt mapping diagnostics
Direct match rate, fallback rate, no-match rate, mean selected variables

Table 3: Example anchored responses
Prompt, selected survey variables, qnet responses, generated answer

Table 4: Ablation
Direct-only vs semantic-fallback answer-only vs fallback update-state
```

---

## 20. Troubleshooting

### YAML will not parse

Run:

```bash
python3 - <<'PY'
import yaml
with open("configs/dtag_config.yaml") as f:
    yaml.safe_load(f)
print("YAML OK")
PY
```

If it fails, fix indentation. YAML is indentation-sensitive.

### `No selected variables remained after intersecting with map ∩ model`

Likely cause: map variable names do not match qnet feature names.

Run the map/qnet intersection check in Section 15.

### `NO_MATCH` for a broad question

If the question is broad but related, semantic fallback should produce an answer. If it does not, try reducing:

```bash
--semantic_min_confidence 0.25
```

or increasing:

```bash
--semantic_prefilter 150
```

Do not use `semantic_fallback update_state` until you have verified fallback quality.

### WVS country/year not changing anything

Check if the model contains hard-conditioning fields:

```bash
python3 - <<'PY'
from quasinet.qnet import load_qnet
m = load_qnet("models/wvs/LSM60K.gz")
features = set(m.feature_names)
for v in ["A_YEAR", "O1_LONGITUDE", "O2_LATITUDE"]:
    print(v, v in features)
PY
```

If these are absent, year/country are metadata/persona text only.

### Afrobarometer country not forced

Check country fields:

```bash
python3 - <<'PY'
from quasinet.qnet import load_qnet
m = load_qnet("models/afrobarometer/LSM_merged_r5_data.gz")
for v in m.feature_names:
    if "COUNTRY" in v.upper() or v.lower() == "country":
        print(v)
PY
```

Then inspect the latest `*.meta.json` and look for `forced_country_variables`.

### GSS ideology fails

Use `--require_polar_vectors` to fail fast when polar vectors are missing or incompatible.

Check that `assets/polar_vectors/polar_vectors.csv` uses exact qnet variable names and exact response strings.

### WVS/Afrobarometer ideology looks meaningless

Do not use GSS polar vectors. Use:

```bash
--no_ideology
```

until survey-specific polar vectors are created.

---

## 21. Minimal command reference

```bash
# List interactive profiles
bin/interactive_config.sh --list

# Run one interactive profile
bin/interactive_config.sh --profile afrobarometer_r5_nigeria --loop

# Ask one question
bin/interactive_config.sh --profile gss2022_wf --question "What do you think about immigration?"

# Run one question-set CSV
bin/interactive_config.sh --profile wvs7_india_2017 --autoplay_csv assets/question_sets/master/01_empirical_right_shift_compact_money_immigration_corruption_tax.csv

# List batch experiments
python3 scripts/run.py --config configs/dtag_config.yaml --list

# Run batch experiment
python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_master

# Postprocess
python3 scripts/post.py --config configs/dtag_config.yaml --experiment gss2022_master

# Generate Afrobarometer map
python3 scripts/getmap_dtag.py --data data/afrobarometer/merged_r5_data.sav --codebook_pdf data/afrobarometer/merged_r5_codebook.pdf --qnet models/afrobarometer/LSM_merged_r5_data.gz --out maps/afromap/afrobarometer_r5_map.csv --text-mode combined

# Generate country specs
python3 scripts/build_country_specs.py --data data/afrobarometer/merged_r5_data.sav --codebook_pdf data/afrobarometer/merged_r5_codebook.pdf --out_json assets/country_specs/afrobarometer/merged_r5_country_specs.json --out_csv assets/country_specs/afrobarometer/merged_r5_country_specs.csv
```
