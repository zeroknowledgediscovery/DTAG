# Polarization question-set optimizer

`optimizer/` searches for a short sequence of survey questions (default up to 10). After a
synthetic DTAG respondent answers the sequence, the aim is that:

- participants whose starting **ideology index is positive** move further **positive**, and
- participants whose starting **ideology index is negative** move further **negative**,

that is, both sides are pushed outward at once. Answers are simulated with the native DTAG model
exactly as the web app does it. Each question is mapped to survey items, each answer is drawn from
the model's conditional distribution and added to the state, and the index is recomputed against
the poles.

> Simulation and model-sensitivity tool for synthetic DTAG respondents. It is **not** intended
> for targeting, persuasion, campaigning or influencing real people. Every report says so too.

Any LLM backend works: OpenAI or OpenAI-compatible servers, Anthropic, any command-line agent, or
any Python function. With the default settings a run needs **no LLM at all**, because persona
states are pinned and the question bank comes straight from the model's map.

## Quick start

From the repository root, with the DTAG requirements installed (`pip install -r requirements.txt`):

```bash
# 1. Sanity check: the model (downloaded on first use), map, poles, participants and LLM ping
python -m optimizer check --provider mock

# 2. Smoke run (~3 min on 4 cores): small search, offline
python -m optimizer run --quick --provider mock --out outputs/optimizer/smoke

# 3. Full run (~30 min on 4 cores) with your own settings
cp optimizer/config.example.yaml my_optimizer.yaml      # edit llm / participants / search
python -m optimizer run --config my_optimizer.yaml

# 4. Validate any existing set (CSV with `question`, optional `variables` column)
python -m optimizer validate --config my_optimizer.yaml \
    --sequence assets/question_sets/polarization/gss2024_polarize_cm_wf_draw_10.csv
```

Tests: `pytest -q optimizer/tests`. A native smoke test runs when `gss/gss_2024` is installed.

Models go to `$DTAG_MODEL_ROOT` (default `~/.cache/dtag/models`) and are downloaded from the public
release when missing (`download: false` turns that off).

## How it works

1. **Participants** (`optimizer/personas/gss2024_spectrum.yaml`: 12 personas, from a rural Alabama
   conservative to a New York liberal). Each has a description (`text`) and, optionally, a pinned
   GSS `state`.
   - With `decode: auto`, a pinned state is used as is. A persona with only `text` is decoded by
     DTAG's own persona decoder through the LLM, which is what the web app does.
   - Every state is validated against the model's support.
2. **Direction** is the sign of the starting index *I0 = (d(sL,s) − d(sR,s)) / d(sL,sR)*, computed
   against the wave's poles (for GSS 2024: `assets/polar_vectors/gss/gss_2024_polar_vectors.csv`).
   - Participants with |I0| < `neutral_band` (default 0.005) are neutral. They are simulated and
     reported but left out of the objective.
   - The GSS 2024 index sits left of zero for most people, so conservatives start only slightly
     positive. Hence the narrow band.
3. **Runs.** Each participant gets several runs. A run starts from a perturbed state: 15% of the
   non-core variables are dropped and 15% resampled from the model (`polviews` and `partyid` are
   never changed). Each run also has its own answer-draw seed. As a result the set has to work
   across nearby respondents and answer luck, not just one fixed trajectory.
4. **Bank.** By default the bank is the model's opinion items, worded from the semantic map.
   - Respondent facts, identity, self-placement, survey meta-data and every variable that defines a
     participant are removed.
   - `rewrite: true` has the LLM rephrase codebook wording as natural questions.
   - `source: file` takes your own questions.
   - `mapping: dtag` / `verify` route each question through DTAG's LLM mapper, so a question is
     answered through the items DTAG would really select in the web app.
5. **Objective.** For each group, the *signed change* (direction × (I_end − I_start)) is averaged
   over runs and turned into a t value. The default `robust` objective is
   **min(t_positive, t_negative)**, so a set must move both sides outward and cannot trade one off
   against the other. All candidates are scored on the same runs (common random numbers).
6. **Search.** It proceeds in four steps:
   - Screen single questions and keep the top `pool`, including the best `per_group` for each side.
   - Greedy forward selection over the best `greedy_pool`.
   - Local search (`budget` replace/swap moves).
   - Pick the prefix length ≥ `min_length` with the best objective on the search runs.
7. **Held-out validation.** The search never sees these seeds: new perturbations and new answer
   draws, `reps` runs per participant. The validation reports:
   - per group, the mean signed change with a 95% bootstrap CI, t and the share of runs moving outward;
   - the separation change (positive − negative mean change) with its CI, for every prefix length;
   - per-participant effects;
   - the set's percentile against `baselines` random sets of the same length.

## LLM backends

Set the `llm:` block in the config, or use `--provider/--llm-model` on the command line.

| provider | what | config |
|---|---|---|
| `openai` | OpenAI, Azure, OpenRouter, Together, Groq, vLLM, LM Studio, Ollama | `model`, `base_url`, `api_key_env` (default `OPENAI_API_KEY`) |
| `anthropic` | Anthropic Messages API over HTTPS (no extra package) | `model`, `api_key_env` (default `ANTHROPIC_API_KEY`) |
| `command` | any CLI agent: prompt on stdin, reply on stdout | `command: "claude -p"`, `timeout` |
| `python` | any function `f(prompt, schema=None, schema_name=..., temperature=...) -> str` | `callable: "pkg.module:func"` |
| `mock` | offline and deterministic, for plumbing tests (its mapping is **not** semantic) | — |

- Structured calls send a JSON schema. Replies are parsed leniently (code fences and surrounding
  prose are fine) and retried when malformed.
- `DTAGClient` adapts any backend to the two OpenAI calls DTAG's core makes, so persona decoding and
  question mapping are DTAG's own code on every backend.
- LLM results are cached in `<out>/llm_cache.json` (or `cache:`), keyed by the map's sha256, so
  re-runs are free.
- Keys are only read from environment variables and never written to outputs.

## Outputs (`out:` folder)

| file | contents |
|---|---|
| `report.md` | the recommended set, held-out validation, every length, participants, baselines |
| `question_set.csv` | `step,question` for the recommended length (loads in the web app's question tools) |
| `question_set_full.csv`, `question_set_detail.csv` | full-length sequence; per step the survey items, mapping and survey wording |
| `validation.json`, `per_length.csv`, `per_participant.csv`, `baselines.csv`, `validation_trajectories.npz` | validation numbers |
| `screening.csv`, `search.json` | search trace |
| `bank.jsonl`, `participants.csv/json` | the bank used (reused on re-runs; `--rebuild-bank`) and the resolved participants |
| `manifest.json`, `log.txt` | git commit, model sha256, map sha256, poles, LLM, full config; run log |

`outputs/` is git-ignored. Copy a finished set into `assets/question_sets/` if you want to keep it.

## Using other waves, poles or participants

- `model: gss/gss_2018` (any installed key). The canonical map and the wave's poles are chosen
  automatically; `map:` / `poles:` override them.
- Your own participants: a YAML list of `{id, text, state?, country?, year?}`.
- Sets are wave-specific, because item availability and the poles change between waves. Re-run
  the optimizer for each wave instead of reusing a set.

## Notes

- `resp_mode: draw` (default) optimizes the expected effect under sampled answers. `max` uses the
  most likely answer, which is deterministic but often flat.
- Effects are population averages. Individual runs vary a lot, so look at the share moving outward.
- With `mapping: source` each question is answered through its own survey item. Before using a set
  in the web app, run `validate` with a real LLM: it maps each question through DTAG and re-scores
  the set on what DTAG actually selects.
