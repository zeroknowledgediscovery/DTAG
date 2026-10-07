# DTAG question-sequence optimization

This application searches for short natural-language question sequences that
drive the GSS-2024 CM and WF digital twins into four directional classes:

1. `both_up`: CM ideology increases and WF ideology increases.
2. `both_down`: CM decreases and WF decreases.
3. `cm_up_wf_down`: CM increases while WF decreases.
4. `cm_down_wf_up`: CM decreases while WF increases.

Every sequence is 5-10 questions. Multiple diverse sets are retained for each
class.

## Design

The workflow separates semantic construction from stochastic evaluation.

### Stage 1: natural-language intervention bank

`generate_question_bank.py` reads the real GSS semantic map and asks an LLM
to turn groups of survey items into ordinary questions that a person could
actually be asked. Every generated question retains the exact GSS variable(s)
that ground it.

This is important for both scientific interpretation and runtime. The LLM is
used to construct readable interventions, not to create synthetic response
probabilities.

Example:

```bash
export OPENAI_API_KEY=...
python applications/question_sequence_optimization/generate_question_bank.py \
  --map maps/gss/gss_2024_map.csv \
  --out outputs/qseq/gss2024_question_bank.jsonl \
  --target 240 \
  --questions_per_batch 10
```

The output JSONL contains `question`, `source_variables`, source survey
items, domain and a short grounding rationale.

### Optional validation: confirm webapp semantic mapping

Before a long search, the generated questions can be passed once through the
same DTAG LLM variable-selection machinery used by the interactive app. This
checks that a natural-language question maps back to the source variables from
which it was generated, without sampling responses or changing state.

```bash
python applications/question_sequence_optimization/validate_question_bank.py \
  --question_bank outputs/qseq/gss2024_question_bank.jsonl \
  --out outputs/qseq/gss2024_question_bank.validated.jsonl \
  --min_source_recall 0.5
```

Add `--require_direct` for the strictest bank: only questions that pass the
normal direct mapper are retained. Use the validated JSONL as the optimizer
input when the eventual sequences are intended for the webapp.

### Stage 2: stochastic sequence search

`optimize_sequences.py` initializes the standard `gss2024_cm` and
`gss2024_wf` profiles once, then freezes those two baseline states for the
experiment. Every replicate resets to exactly those initialized states.

For each question in a sequence:

1. condition the native LSM on the current respondent state;
2. obtain the conditional distribution for the question's retained source
   variable(s);
3. draw a stochastic response;
4. update respondent state;
5. recompute the ideology coordinate;
6. continue to the next question from that updated state.

Thus sequence effects are path-dependent. They are not sums of independent
single-question effects.

The expensive LLM variable-selection and prose-rendering calls are intentionally
not repeated inside the Monte Carlo loop. The natural-language question and its
grounding are fixed in Stage 1; Stage 2 samples the native LSM directly. This
makes tens of thousands of state-changing trajectories practical while keeping
the interventions human readable.

Example screening run:

```bash
python applications/question_sequence_optimization/optimize_sequences.py \
  --question_bank outputs/qseq/gss2024_question_bank.jsonl \
  --outdir outputs/qseq/search01 \
  --individual_reps 30 \
  --screen_reps 50 \
  --confirm_reps 300 \
  --random_sequences 1000 \
  --sets_per_category 6
```

A stronger final run:

```bash
python applications/question_sequence_optimization/optimize_sequences.py \
  --question_bank outputs/qseq/gss2024_question_bank.jsonl \
  --outdir outputs/qseq/search_final \
  --individual_reps 100 \
  --screen_reps 200 \
  --confirm_reps 2000 \
  --random_sequences 5000 \
  --elite 100 \
  --mutations_per_elite 20 \
  --sets_per_category 10 \
  --bootstrap 5000
```

## Statistical outputs

For each sequence and each persona the optimizer reports:

- mean final displacement from the initialized ideology coordinate;
- standard deviation over stochastic trajectories;
- bootstrap confidence interval for the mean displacement;
- probability that a replicate lands in the requested directional quadrant;
- Wilson confidence interval for that quadrant probability.

By default, a sequence is called `robust` only when the CM and WF directional
mean confidence intervals both exclude an effect floor of +/-0.005 in the
required directions.

The optimizer first screens individual questions, builds category-specific
candidate pools, samples many random 5-10 question sequences, mutates the best
sequences, and finally re-runs the best candidates with the larger confirmation
Monte Carlo sample.

Final sets are diversity-filtered by Jaccard overlap so that the output contains
multiple meaningfully different sequences rather than trivial reorderings of
the same questions.

## Outputs

`initialization.json`
: Frozen CM/WF initial states and initial ideology values used for every
replicate.

`screen_results.csv`
: All random and mutated sequences evaluated at the screening sample size.

`confirmed_results.csv`
: High-ranked sequences evaluated at `--confirm_reps`.

`selected_sets.json`
: Final retained sets and their uncertainty statistics.

`question_sets/<category>/set_XX.csv`
: Ready-to-use 5-10 question sequences with question IDs and source variables.

## Notes

The sign convention is the existing DTAG ideology coordinate. "Up" and "down"
therefore mean increasing or decreasing DTAG ideology coordinate, not labels
such as conservative/liberal inserted by this optimizer.

The paired CM/WF replicate seeds are reproducible but intentionally offset
between the two respondents. This prevents identical pseudo-random draws from
creating artificial coupling while preserving a deterministic experiment.

Questions grounded in overlapping variables are excluded from the same
sequence by default. Use `--allow_variable_overlap` only when repeated
intervention on the same latent survey construct is scientifically intended.
