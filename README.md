# DTAG clean experiment setup

This is a config-driven DTAG rerun package. The master configuration is:

```text
configs/dtag_config.yaml
```

Use that one YAML file to set the LSM/qnet model paths, map files, question-set folders, personas, run parameters, and postprocessing/plotting options.

## Directory layout

```text
DTAG_clean_setup_v2/
  configs/
    dtag_config.yaml                 Master experiment config
  scripts/
    pipeline.py                      DTAG pipeline, formerly pipeline6iloc.py
    run.py                           Run an experiment from dtag_config.yaml
    run_grid.py                      Parallel grid launcher
    post.py                          Postprocess an experiment from dtag_config.yaml
    postprocess.py                   Regression/divergence summaries plus plots
    make_map.py                      Map generator, formerly getmap.py
    smoke_test.py                    OpenAI API smoke test
  maps/                              Variable-to-question maps
  models/
    gss/                             Put GSS qnet/LSM files here
    wvs/                             Put WVS qnet/LSM files here
  assets/
    polar_vectors/                   Put real polar_vectors.csv here
    question_sets/
      original/
      divergence/
    label_maps/
  outputs/                           Run outputs
```

The older long script names are still present for provenance, but the recommended names are the simple ones above.

## One-time setup

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="..."
bin/run_smoketest.sh gpt-4.1-mini
```

Copy model files into the paths specified under `models:` in `configs/dtag_config.yaml`. For the included GSS 2022 experiments, expected files are:

```text
models/gss/gss_2022female.pkl.gz
models/gss/gss_2022male.pkl.gz
```

Copy the model-compatible polar vectors to:

```text
assets/polar_vectors/polar_vectors.csv
```

The template file is not sufficient for real runs; response values must match the qnet model support.

## Run by master config

List configured experiments:

```bash
bin/list_experiments.sh
```

Run the default divergence experiment:

```bash
bin/run_config.sh gss2022_divergence
```

Equivalent direct command:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_divergence
```

Dry-run without executing jobs:

```bash
python3 scripts/run.py \
  --config configs/dtag_config.yaml \
  --experiment gss2022_divergence \
  --dry-run
```

Postprocess and make plots:

```bash
bin/post_config.sh gss2022_divergence
```

Dark transparent plots for slides:

```bash
bin/post_config.sh gss2022_divergence --dark --transparent
```

## Editing the master config

The most important sections are:

```yaml
models:
  gss_2022_female: models/gss/gss_2022female.pkl.gz

maps:
  gss_2022: maps/map2022.csv

question_sets:
  divergence:
    dir: assets/question_sets/divergence
    glob: "diverge_set_*.csv"

experiments:
  gss2022_divergence:
    map: gss_2022
    question_set: divergence
    outdir: outputs/dtag_gss2022_divergence
    personas:
      - id: WF_US_2022
        qnet: gss_2022_female
        persona: ...
```

To run a different year, add model paths under `models:`, add or update a map under `maps:`, then define a new experiment under `experiments:`. The same `question_set:` can be reused across years.

To explore new question sets, place CSVs under a new folder, add that folder under `question_sets:`, then point an experiment to it.

## Map generation

Use the simplified map generator:

```bash
python3 scripts/make_map.py \
  --dta data/raw/GSS2024.dta \
  --codebook_pdf data/raw/GSS_2024_Codebook.pdf \
  --out maps/map2024.csv
```

Then add the new map to `configs/dtag_config.yaml`:

```yaml
maps:
  gss_2024: maps/map2024.csv
```

## Important notes

For year-specific GSS models, year and sex are usually encoded in the selected qnet file. The packaged `pipeline.py` soft-skips hard `A_YEAR` and longitude/latitude forcing if the model lacks those features. This allows the same config format to work for GSS and WVS-style models.

For WVS-style pooled models with explicit `A_YEAR`, `O1_LONGITUDE`, and `O2_LATITUDE`, persona fields such as `year`, `country`, and `continent` are used as hard conditioning when those features exist.

Use the same variant for quadrant and summary plots when reconciling figures. In `dtag_config.yaml`, set both:

```yaml
postprocess:
  plot_variant: forward
  quadrant_variant: forward
```

If you want a quadrant aggregated across forward, reverse, and shuffle variants, set `quadrant_variant: all`, but then it will not match the forward-only signed-shift summaries exactly.


## Master question set

The clean combined question set is now:

```text
assets/question_sets/master/
```

It contains both the original DTAG question sets and the divergence probes. The original filenames were renamed to content-based names, and all master files are numbered so sorting is stable. Manifests and label maps are kept outside the runnable question folder to prevent accidental execution as question files.

Run the combined master experiment:

```bash
bin/run_gss2022_master.sh
bin/postprocess_master.sh gss2022_master
```

The corresponding label map is:

```text
assets/label_maps/question_set_interpretive_name_map_master.csv
```

The old-to-new filename mapping is:

```text
assets/label_maps/question_set_master_rename_manifest.csv
```

## Config-driven interactive profiles

Use `scripts/interactive.py` or `bin/interactive_config.sh` to avoid long handwritten pipeline commands.

```bash
bin/interactive_config.sh --list
bin/interactive_config.sh --profile afrobarometer_r5_nigeria --loop
bin/interactive_config.sh --profile wvs7_india_2017 --loop
bin/interactive_config.sh --profile gss2022_wf --question "What do you think about immigration?"
```

See `CONFIG_PROFILES.md` for the full profile/experiment workflow.
