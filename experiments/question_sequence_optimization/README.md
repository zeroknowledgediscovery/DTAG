# DTAG synthetic trajectory-sequence study

This folder is the entry point for the DTAG experiment that studies how short
question sequences alter the trajectories of two fixed synthetic GSS-2024
respondent initializations, CM and WF, under stochastic native-LSM state updates.

This is a simulation and model-sensitivity study. It is intended for analyzing
DTAG dynamics, reproducibility, path dependence, and uncertainty in synthetic
respondents. It is not intended for targeting or persuading real people.

## Code locations

The current generalized experiment code is in:

```
applications/question_sequence_optimization/
├── generate_question_bank.py
├── validate_question_bank.py
├── optimize_sequences.py
└── README.md
```

Earlier DTAG optimization/sensitivity code and documentation already present in
the repository are:

```
scripts/optimize_question_sets.py
QUESTION_OPTIMIZATION.md
```

Existing result assets are under:

```
assets/question_sets/optimized/
assets/question_sets/polarization/
assets/question_sets/depolarization/
```

## What the experiment measures

Starting from the fixed synthetic profiles `gss2024_cm` and `gss2024_wf`,
we evaluate ordered question sets of length 5-10 under four sign patterns for
the final DTAG ideology-coordinate displacement:

- both positive
- both negative
- CM positive / WF negative
- CM negative / WF positive

For every stochastic replicate, the respondent is reset to its initialized
state, responses are drawn from native conditional distributions, each response
updates state, and ideology is recomputed before the next question. Therefore
the measured effect is path dependent rather than a sum of independent
single-question effects.

## Natural-language question construction

`generate_question_bank.py` converts real GSS survey items into readable
natural-language questions while retaining their exact source variables.

Typical use:

```bash
python applications/question_sequence_optimization/generate_question_bank.py \
  --map maps/gss/gss_2024_map.csv \
  --out outputs/qseq/gss2024_question_bank.jsonl \
  --target 240
```

The LLM is used only for semantic construction of readable questions.

## Semantic validation

`validate_question_bank.py` checks generated questions through the normal
DTAG semantic-mapping machinery and verifies that they map back to the expected
source variables.

```bash
python applications/question_sequence_optimization/validate_question_bank.py \
  --question_bank outputs/qseq/gss2024_question_bank.jsonl \
  --out outputs/qseq/gss2024_question_bank.validated.jsonl \
  --min_source_recall 0.5 \
  --require_direct
```

This step is useful before any large native-LSM simulation because it checks
that the human-readable form behaves consistently with the interactive DTAG
mapping path.

## Stochastic sequence search

`optimize_sequences.py` performs the native-LSM Monte Carlo search. It keeps
the natural-language question mapping fixed and avoids repeated LLM calls inside
the replicate loop.

Each replicate performs:

1. reset to the frozen CM or WF initialized state;
2. compute native conditional response distributions;
3. draw a response;
4. update respondent state;
5. recompute the DTAG ideology coordinate;
6. continue through the ordered question sequence;
7. measure final displacement from the initial state.

Outputs include:

- mean CM and WF displacement;
- standard deviation;
- bootstrap confidence intervals;
- requested-quadrant occupancy probability;
- Wilson confidence intervals;
- multiple diversity-filtered candidate sequences.

Example large simulation:

```bash
python applications/question_sequence_optimization/optimize_sequences.py \
  --question_bank outputs/qseq/gss2024_question_bank.validated.jsonl \
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

## Existing DTAG results

A substantial earlier study was already carried out and is documented in
`QUESTION_OPTIMIZATION.md`. It includes:

- GSS ideology-pole corrections;
- the v2 pole definition;
- deterministic modal-response sequence search;
- stochastic answer sampling;
- rich and perturbed synthetic personas;
- local sequence search;
- held-out validation;
- random-sequence baselines;
- independent CM/WF sampling streams.

The strongest already validated opposite-direction synthetic trajectory sets
are stored in:

```
assets/question_sets/polarization/gss2024_polarize_cm_wf_draw_10.csv
assets/question_sets/depolarization/gss2024_depolarize_cm_wf_draw_12.csv
```

The corrected confidence-interval summaries are:

```
assets/question_sets/polarization/corrected_summary.json
assets/question_sets/depolarization/corrected_summary.json
```

Earlier same-direction modal-response candidates are:

```
assets/question_sets/optimized/gss2024_same_both_up.csv
assets/question_sets/optimized/gss2024_same_both_down.csv
```

Those same-direction candidates have not yet received the same held-out
stochastic validation as the opposite-direction sets.

## Relationship between old and new code

Do not replace `scripts/optimize_question_sets.py`. It contains important
historical methodology and validation logic.

The newer `applications/question_sequence_optimization/` code adds a cleaner,
generalized workflow for:

- constructing a reusable natural-language question bank;
- validating question-to-variable mappings once;
- running large native-LSM Monte Carlo searches efficiently;
- treating all four synthetic directional classes uniformly;
- returning multiple diverse 5-10-question sequences per class.

## Recommended next analysis

The main unfinished technical work is:

1. stochastic held-out validation of the existing same-direction candidates;
2. re-search of the two same-direction classes if those candidates are weak
   under stochastic sampling;
3. multiple diverse alternatives per class rather than a single sequence;
4. final webapp mapping checks on the retained natural-language questions;
5. plots of mean trajectory, confidence bands, and class occupancy probability.

All resulting claims should remain explicitly about synthetic DTAG trajectories
under the GSS-2024 native model.
