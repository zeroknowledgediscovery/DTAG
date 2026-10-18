# DTAG command-line reference

`pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@dev"` installs four commands.
From a source checkout, use the script shown in each section instead.

| Command | Purpose | From a clone |
|---|---|---|
| `dtag-experiment` | Run web-app experiments (pushes, sequences, recipes) without the browser | `python scripts/dtag_experiment.py` |
| `dtag-web` | Start the web workbench and HTTP API | `cd webapp && ./run.sh` |
| `dtag-models` | List and download native survey models | `python scripts/fetch_models.py` |
| `dtag-doctor` | Readiness and installation checks | `python scripts/check_dtag_readiness.py` |
| `python -m optimizer` | Search for polarizing/depolarizing question sets (repository root only) | same |

Every command takes `-h` / `--help`. An OpenAI key (`export OPENAI_API_KEY=...`) is needed for real
runs of `dtag-experiment` and `dtag-web`. Models download on first use to `~/.cache/dtag/models`
(change with `DTAG_MODEL_ROOT`).

---

## dtag-experiment

Uses the same runner as the web app's *Experiment* tab. Each run starts a fresh respondent with
seed `base + run`, and pushes are re-chosen at that run's own state. Each run prints its questions
with the ideology before and after each one. Results go to `./experiments/<name>_<timestamp>/`.
Ctrl-C stops after the current action and keeps the finished runs.

### Subcommands

| Subcommand | What it does |
|---|---|
| `push` | Auto-push the respondent's ideology up or down for N steps per run |
| `sequence` | Ask a fixed list of questions per run |
| `run RECIPE.json` | Replay a recipe, e.g. downloaded from the web app's Experiment tab or written with `--dry-run` |
| `profiles` | List the respondent presets |

### Respondent options (`push`, `sequence`)

Give either `--profile`, or a description (`--persona` plus optional `--country`/`--year`/`--date`).

| Option | Meaning |
|---|---|
| `--profile NAME` | Preset, e.g. `gss2024_cm`, `gss2018_wf` (list: `dtag-experiment profiles`) |
| `--persona TEXT` / `--persona-file FILE` | Who: free-text description (overrides the preset's) |
| `--country`, `--year`, `--date YYYY-MM-DD` | Where and when |
| `--model KEY` | Survey model, e.g. `gss/gss_2018` (default: the preset's, or the recommended one) |
| `--resp-mode draw\|max` | Draw anchor answers from the native distribution, or take the modal answer |
| `--set KEY=VALUE` | Any other profile setting, repeatable (e.g. `--set semantic_fallback=off`, `--set k=30`) |

### push options

| Option | Default | Meaning |
|---|---|---|
| `--direction up\|down\|right\|left` | required | `up`/`right` raises the ideology index; `down`/`left` lowers it |
| `--steps N` | 5 | Push questions per run |
| `--mode realistic\|validated\|direct` | realistic | Push mode, as in the web app's Auto-push tab |
| `--include-pole-items` | off | Allow items that define the ideology poles |
| `--then-questions FILE` | — | After the push, ask this question sequence |

### sequence options

| Option | Meaning |
|---|---|
| `--questions FILE` | One question per line (`#` comments and blank lines are skipped), or a JSON list; `-` reads stdin |
| `-q "QUESTION"` | A question; repeatable, and asked before `--questions` |

### Experiment options (all of `push`, `sequence`, `run`)

| Option | Default | Meaning |
|---|---|---|
| `--runs N` | 1 | Independent runs (max 200) |
| `--seed N` | random | Base seed; run k uses N+k |
| `--name NAME` | derived | Output folder prefix |
| `--out DIR` | `./experiments` | Results folder (or `$DTAG_EXPERIMENTS_DIR`) |
| `--llm-model NAME` | configured | OpenAI model for mapping and prose |
| `--mock` | off | Offline mock LLM: placeholder prose and mapping; for plumbing tests only |
| `--dry-run` | off | Print the recipe JSON and exit, without running |
| `--quiet` | off | Don't print each run's questions |

Exit status: 0 = done, 130 = interrupted, 1 = error.

### Examples

```bash
dtag-experiment profiles
dtag-experiment push --profile gss2024_cm --direction left --steps 3 --runs 2 --mock
dtag-experiment push --profile gss2024_cm --direction down --steps 10 --runs 20 --seed 1
dtag-experiment push --persona "35 year old nurse in Ohio, moderate" --country "United States" \
    --year 2024 --direction up --steps 5 --runs 5
dtag-experiment push --profile gss2024_wf --direction right --steps 3 --then-questions qs.txt
dtag-experiment sequence --profile gss2018_wf --questions qs.txt --runs 10
dtag-experiment sequence --profile gss2024_cm -q "Should marijuana be made legal?" -q "Do you favor the death penalty?"
dtag-experiment run dtag_recipe_gss2024_cm.json --runs 50
dtag-experiment push --profile gss2024_cm --direction up --dry-run > my_recipe.json   # edit, then: run my_recipe.json
```

### Recipe format (for `run`)

```json
{"name": "my_exp",
 "respondent": {"spec": { ...as written by --dry-run or the web app... }},
 "actions": [
   {"ask": "question text"},
   {"sequence": ["question 1", "question 2"]},
   {"push": "up", "mode": "realistic", "include_pole_items": false},
   {"auto_push": "down", "steps": 5, "mode": "realistic", "include_pole_items": false},
   {"next": "open"},
   {"reset": true}
 ]}
```

`next` asks the web app's informative next question (`open` or `connected`). A file of the form
`{"recipe": {...}, "runs": N}` (the API request body) is also accepted.

### Output folder

| Path | Contents |
|---|---|
| `report.md` | Actions, ideology mean/sd/95% CI after each action, net change, push hit rate, questions asked |
| `recipe.json`, `manifest.json` | What was run; seeds, model, git commit, status |
| `summary/steps.csv` | One row per question asked (run, action, question, items, ideology before/after) |
| `summary/checkpoints.csv`, `summary/stats.csv` | Ideology after each action, per run and aggregated |
| `summary/questions.csv`, `summary/final_answers.csv` | Questions asked per action; final answer frequencies |
| `summary/state_changes.csv`, `summary/states.csv` | Every answer change; the full survey state after every question |
| `runs/run_NN/` | Per-run `trace.jsonl`, state files and the web app's full session log |

---

## dtag-web

| Option | Default | Meaning |
|---|---|---|
| `--host H` | `127.0.0.1` (`$DTAG_HOST`) | Bind address; use `0.0.0.0` to serve others (set `DTAG_PASSWORD` first) |
| `--port P` | 8000 (`$DTAG_PORT`) | Port; the UI is at `/` and the API docs at `/docs` |
| `--reload` | off | Development auto-reload |

Set `DTAG_LLM_BACKEND=mock` to try it without an OpenAI key. From a clone, `cd webapp && ./run.sh`
does the same (`./run.sh --dev` also starts the Vite dev server).

## dtag-models

| Usage | Meaning |
|---|---|
| `dtag-models --list` | Catalog of models (`*` = installed) |
| `dtag-models gss/gss_2024` | Download one model |
| `dtag-models --family gss\|afrobarometer\|wvs\|eurobarometer` | Download a whole family |
| `dtag-models --all` | Download every model |
| `--force` | Re-download even if installed |
| `--root DIR` | Install location (default `$DTAG_MODEL_ROOT` or `~/.cache/dtag/models`) |
| `--release TAG` | Use a specific public model release |

## dtag-doctor

No options. Checks files, Python packages, the native bindings, models, maps and poles, then runs
the clean-surface audit. Exits non-zero on failure. From a clone, run
`python scripts/check_dtag_readiness.py` and `python scripts/audit_clean_repo.py`.

## python -m optimizer

Run from the repository root. Searches for question sequences that move a population of personas
apart (or together). Full details are in `optimizer/README.md`.

| Command | What it does |
|---|---|
| `check` | Validate the model, map, poles, participants and LLM setup |
| `bank` | Build and map the question bank only |
| `run` | Bank → search → validation → report (`report.md`, `question_set.csv`) |
| `validate --sequence FILE.csv` | Validate a given question sequence (CSV with a `question` column) |

| Option | Meaning |
|---|---|
| `--config FILE` | YAML config (`optimizer/config.example.yaml` needs no LLM; `configs/optimizer_gss2024_*.yaml` decode personas with a real LLM) |
| `--out DIR` | Output folder (overrides the config) |
| `--quick` | Small smoke-test settings |
| `--provider openai\|anthropic\|command\|python\|mock`, `--llm-model NAME` | Switch the LLM without editing the config |
| `--workers N` | Worker processes (default: all cores) |
| `--rebuild-bank` | Rebuild the bank even if `bank.jsonl` exists |

```bash
python -m optimizer check --config optimizer/config.example.yaml
python -m optimizer run --config optimizer/config.example.yaml --quick --out outputs/optimizer/test
```

The research runner `python -m optimizer.sequence_library_runner --help` (fixed-sequence library for
GSS 2016/2018/2024) is documented in `optimizer/SEQUENCE_LIBRARY_RUNNER.md`.
