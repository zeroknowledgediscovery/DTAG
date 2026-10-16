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

1. **Participants** (the YAML specified by participants.file; the new CM/WF asset file uses actual LLM decoding). Each has a description (`text`) and, optionally, a pinned
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
3. **Runs.** Each participant gets multiple starting states and/or answer draws. LLM-decoded persona assignments
   are protected, including `polviews` and `partyid`; only unprotected context can vary. Each run also has its own answer-draw seed. As a result the set has to work
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
   draws, `reps` runs per participant. The validation reports state-clustered estimates when multiple starting states are requested:
   - per group, the mean signed change with a 95% bootstrap CI, t and the share of runs moving outward;
   - the separation change (positive − negative mean change) with its CI, for every prefix length;
   - per-participant effects;
   - the set's percentile against `baselines` random sets of the same length;
   - state-level means, sign flips, and shuffled-order controls.

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
| `validation.json`, `per_length.csv`, `per_participant.csv`, `per_state.csv`, `baselines.csv`, `order_baselines.csv`, `state_diagnostics.json`, `starting_states.jsonl`, `validation_trajectories.npz` | validation numbers and auditable starting states |
| `screening.csv`, `search.json` | search trace |
| `bank.jsonl`, `bank_fingerprint.json`, `participants.csv/json` | the bank used (fingerprinted and rebuilt on configuration/map changes) and actual protected LLM-decoded assignments |
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


## CM/WF asset personas and robustness audit (October 2026)

The repository includes rich source descriptions and expected 15-item state assignments in
`assets/question_sets/personas/`. To use them without copying fixed starting states, set
`participants.file: optimizer/personas/gss2024_asset_cm_wf.yaml` and `participants.decode: auto`.
The entries have `text_file`, not pinned `state`: the same DTAG persona mapper used by the web app
runs under the configured LLM at check/run time. Each real decoded assignment is saved in
`participants.json` and its variable and value is immutable during initial-state perturbation
and all question responses. `polviews` and `partyid` must match `target_states.json`; other
disagreements appear in `participants.json` as `expected_mismatches`. With no LLM/API key,
the CM/WF asset configuration cannot decode or run. Previously pinned states remain supported.

### Versioned experiment configurations

`configs/optimizer_gss2024_cm_wf_baseline.yaml` preserves the original 2/4-draw,
60-move search that produced the initial results. The canonical expanded-search
configuration is `configs/optimizer_gss2024_cm_wf_robust.yaml` (screen draws 20,
search draws 40, local budget 100). Its output directory is separate:
`outputs/optimizer/gss2024_cm_wf_robust`, so earlier results are not overwritten.
Increasing repetitions mitigates sampling noise, but does **not** itself resolve
zero-variance / infinite-t search scores; interpret those scores cautiously.

Use the canonical file directly, or copy it into `my.yaml` as a local working copy.
All repository-relative paths in the YAML are resolved from the repository root.

```bash
# From the repository root
cp configs/optimizer_gss2024_cm_wf_robust.yaml my.yaml
# Set OPENAI_API_KEY in your shell without committing or printing its value
python -m optimizer check --config my.yaml
python -m optimizer run --config my.yaml --rebuild-bank --workers 4
python -m optimizer validate --config my.yaml \
  --sequence outputs/optimizer/gss2024_cm_wf_robust/question_set.csv \
  --out outputs/optimizer/gss2024_cm_wf_robust_remapped --workers 4
```

For a no-copy run, replace `--config my.yaml` with
`--config configs/optimizer_gss2024_cm_wf_robust.yaml`.


The optimizer run searches a sequence, then validates it. The separate validate call
re-maps the final exported question wording through DTAG's actual direct LLM mapper, as the
web app does. Omitting `--out` on validate automatically writes below the configured output
under `validation/<sequence_filename>` rather than overwriting the optimized report.

### Additional YAML settings

```yaml
participants:
  core_variables: [polviews, partyid]
  protect_mapped: true            # protect all actual decoded persona assignments
  perturb: {drop: 0.15, resample: 0.15}
validate:
  states_per_persona: 50         # independent seeded initializations per asset persona
  reps_per_state: 20            # response-draw replicates at each initial state
  augment_count: 6              # conditionally sample additional non-question context variables
  order_baselines: 5            # randomly re-ordered versions of the selected set
  baselines: 20                 # random sets drawn from the same bank
  baseline_reps: 4              # response draws per matched starting state for those controls
```

All protected LLM-decoded variables retain their exact original categorical labels.
Nonprotected context variables are sampled from model conditional distributions, excluding
all candidate-question variables, ideology-pole variables and persona anchors. When
`states_per_persona > 1`, a starting-state fingerprint merges duplicate assignments
into a single statistical cluster; validation reports the actual number of distinct
states, not just the number of seeds tried.

Directional change is defined from each *actual initialized state's* ideology index,
not the original persona's index. For nonneutral starting index I0 and final index Iend:

    outward = sign(I0) * (Iend - I0)

A positive result indicates movement away from zero for that simulated trajectory.
The report also counts initializations whose actual ideology sign differs from the
original persona sign (including those entering the neutral band).

Inspect `report.md` and `per_state.csv` first. Group-level bootstrap confidence intervals
for multi-state validation resample distinct starting states, never repeated answer draws
as independent cases. `starting_states.jsonl` stores the actual state and anchors for each
cluster. `state_diagnostics.json` reports starting-state counts and outward fractions.
`order_baselines.csv` evaluates the importance of question order.

These diagnostics describe uncertainty across generated contexts conditional on the two
source personas and a fixed learned LSM. They do NOT guarantee outward movement for every
initialization, demonstrate changes to real respondents' political opinions, or establish
population representativeness. For such generalization, use separate measured respondents
and validation independent of the model's synthetic conditional distributions.

### Comparing with the historical ten-question set

```bash
python -m optimizer validate --config my.yaml \
  --sequence assets/question_sets/polarization/gss2024_polarize_cm_wf_draw_10.csv \
  --out outputs/optimizer/historical_asset_audit
```

This matches the new asset personas and the same validation seeds, although its remapped
questions may select different survey variables. Check `question_set_detail.csv` in both runs.

## Deferred research follow-ups

The four directional ideology-index regimes, explanations to investigate for the
small observed movements, t-statistic degeneracy, persona-anchor tradeoffs,
pole-variable overlap, matched baselines, and expanded starting-state coverage
are tracked in [DEFERRED_RESEARCH_NOTES.md](DEFERRED_RESEARCH_NOTES.md).
These are **future research diagnostics**, not prerequisites for the current
reproducible CM/WF baseline or automatic changes to the optimizer configuration.


## Four-way descriptive audit of pre-existing sequences

The repository already contains four types of historical GSS 2024 question sequences.
They were constructed using older, generally noncomparable starting states and response modes.
They are listed as **historical inputs, not new validated discoveries** in
[four_way_catalog.yaml](four_way_catalog.yaml). The current ten-question run is the
contemporary divergence input; it resides locally under
outputs/optimizer/gss2024_cm_wf_robust/.

The **four-way audit does not optimize or generate sequences**. It reads the raw
ideology-index trajectories for preselected sequence evaluations and classifies their
observed mean changes using the actual sign of each initialized state:

| Regime | Positive-start raw change | Negative-start raw change |
|---|---|---|
| Divergence | positive | negative |
| Positive translation | positive | positive |
| Negative translation | negative | negative |
| Convergence | negative | positive |

Convergence can overshoot the neutral point; the JSON report includes the fraction
crossing zero. Positive group means alone are not sufficient for a reliable regime
classification: an outcome is marked supported only when both state-bootstrap 95%
intervals exclude zero. Missing validation outputs remain explicitly unevaluated.

To summarize any already available runs:

    python -m optimizer.four_way_audit --catalog optimizer/four_way_catalog.yaml \
      --out outputs/optimizer/four_way_summary

If the three historical inputs have not yet been rerun under the current model
and protected LLM-decoded persona protocol, they are evaluated *as fixed inputs*
with these validation-only commands (from repository root):

    python -m optimizer validate --config configs/optimizer_gss2024_four_way_audit.yaml \
      --sequence assets/question_sets/optimized/gss2024_same_both_up.csv \
      --out outputs/optimizer/four_way_evaluations/positive_translation --workers 4

    python -m optimizer validate --config configs/optimizer_gss2024_four_way_audit.yaml \
      --sequence assets/question_sets/optimized/gss2024_same_both_down.csv \
      --out outputs/optimizer/four_way_evaluations/negative_translation --workers 4

    python -m optimizer validate --config configs/optimizer_gss2024_four_way_audit.yaml \
      --sequence assets/question_sets/depolarization/gss2024_depolarize_cm_wf_draw_12.csv \
      --out outputs/optimizer/four_way_evaluations/convergence --workers 4

    python -m optimizer.four_way_audit --catalog optimizer/four_way_catalog.yaml \
      --out outputs/optimizer/four_way_summary

The audit config uses sampled answers, real DTAG question mapping, 50 starting-state
attempts per persona and 20 draws per state. It does not perform a new search.
Its output directories are separate from the saved ten-question run. Because the
optimizer excludes mapped question variables when augmenting initial context,
the independently evaluated sequences are **not guaranteed to use exactly matched
starting states**, even with the same seed. Do not claim a paired comparison.
Descriptions refer to *model-inferred ideology-index changes*, not belief change.

**Archiving:** outputs are intentionally excluded by .gitignore. Preserve the
ten-question run separately before making changes, for example:

    tar -czf ../gss2024_cm_wf_robust_results.tar.gz \
      outputs/optimizer/gss2024_cm_wf_robust
    sha256sum ../gss2024_cm_wf_robust_results.tar.gz

Do not label a four-way collection "complete under the current protocol" until
all four validation outputs exist and have been checked for mapping/anchor integrity.

## Multi-year descriptive results inventory

For a local-first, non-optimizing coverage report spanning GSS 2016, 2018,
and 2024 (four raw-change regimes `++`, `+-`, `-+`, `--`), see
[MULTIYEAR_REGIME_LIBRARY.md](MULTIYEAR_REGIME_LIBRARY.md).
The script `python -m optimizer.multiyear_regime_summary` inventories saved
trajectory validations, reports confirmed regime counts and missing cells,
and assigns a 0–10 methodological evidence-quality score. It does not
select or generate question sequences by political direction.
