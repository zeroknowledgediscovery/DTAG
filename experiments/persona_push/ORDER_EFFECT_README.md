# DTAG: Ten-question order-dependence experiment

This follow-up isolates the **order** of survey-item conditioning from the
**identity** of the ten survey items. It does not use a language model and it
does not test persuasion in humans.

## Existing-data check

The previously completed GSS 2024 6-persona × 4-policy × 40-repetition run
contains 960 fully observed trajectories of exactly ten questions each.

Grouping by persona, policy, and *unordered ten-item set* found:

| Policy | Question sets that occurred in ≥2 distinct orders | Runs involved |
|---|---:|---:|
| Right push | 8 | 18 |
| Left push | 19 | 56 |
| Near-zero expected-drift | 29 | 232 |
| Random question | 0 | 0 |

Those comparisons are **not causal**: the response vectors also vary across
runs. Holding all ten question–answer assignments fixed must yield the same
terminal partial state and the same native ideology index regardless of order.

## Native replay design

The checked-in `fixed_10q_order_sets.json` freezes the ten questions asked
in repetition 0 for **each of six pinned personas × each of right/left/neutral
selection** (18 sets). This selection uses the previously recorded question
identities, **not** the observed final ideology outcomes.

Each fixed ten-item set is replayed using:

- the originally observed question order;
- its exact reverse;
- two independently generated, deterministic random permutations.

For each ordering, 40 replicates sample **each answer** from the native LSM
conditional distribution given all previously sampled responses at that
point in the permutation. For every persona, source set, repetition, and
question *variable*, the same pseudorandom uniform draw is used across all
four permutations (variance-reducing common random numbers). Responses are
**not** artificially fixed; they may change because conditional distributions
change. Across source sets there may be overlap and correlated draws.

The primary contrast is

`mean_r [ I(final_order_r) - I(final_original_r) ]`

with a 95% percentile bootstrap CI resampling complete repetitions, rather
than treating ten individual questions as independent observations. Answer
assignment changes are counted per matched repetition, by source set and
permutation.

A structural control applies the identical **pre-recorded responses** to the
ten items in both forward and reversed insertion order and verifies that the
native index is unchanged to floating point tolerance. This control
distinguishes changes in the *answer distribution induced by sequential
conditioning* from a purely cosmetic reordering of state construction.

### Interpretation

If all native conditionals were consistent with a single static joint
distribution and sequential draws sampled exactly from it, the terminal
distribution of the ten variables would be invariant under their order.
Significant differences in mean terminal ideology across orderings can
therefore indicate an **order-sensitive sampling geometry** or
incoherent fitted conditionals. They are **not evidence that real
respondents' beliefs changed**. Four preselected orders do not exhaust
all ten-factorial permutations. CIs are **pointwise**; results across
18 sources × 3 contrasts require multiplicity awareness.

## Run on the machine with DTAG native models

```bash
git checkout dev && git pull --ff-only origin dev
python scripts/dtag_fixed_10q_order_test.py \
  --model gss/gss_2024 --reps 40 --workers 4 \
  --bootstrap 2000 --seed 20261021 \
  --out outputs/dtag_persona_push/order_replay_10q
```

For a minimal correctness check (not inferential results):

```bash
python scripts/dtag_fixed_10q_order_test.py \
  --quick --workers 2 \
  --out outputs/dtag_persona_push/order_replay_smoke
```

The GitHub Actions workflow is
`.github/workflows/dtag-fixed-10q-order.yml`. All outputs are uploaded
as the run artifact `dtag-fixed10-order-replay`. Data outputs:

- `fixed_orders.json`: all 18×4 exact ten-question orderings
- `run_endpoints.csv`: one record for each complete replay and its final I
- `question_draws.csv`: each sampled item and native conditional probability
- `endpoint_summary.csv`: mean terminal drift per source-set/order with CI
- `paired_order_contrasts.csv`: paired original-vs-permuted endpoint
  difference, 95% CI, and fraction/count of changed sampled answers
- `omnibus_order_spread.csv`: observed max-minus-min mean across four orders
- `fixed_10q_order_effects.pdf/.png`: 6×3 grid of paired order effects
- `manifest.json`: exact model and file hashes, seeds, code SHA and statistics
