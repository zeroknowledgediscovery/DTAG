# Empirical-style GSS 2018 pole experiment: results and decision

The experiments here use the **public GSS 2018 native LSM** to compute
model-implied conditional categorical distributions. These are not
survey-weighted estimates from raw 2018 respondent microdata.

Executed in [GitHub Actions run 38913790951](https://github.com/zeroknowledgediscovery/DTAG/actions/runs/38913790951)
using the independently maintained scratch/ scripts. The run archives
the proposed pole CSV, conditional probability tables, per-anchor
orientation diagnostics, persona index comparisons, and reports.

## Construction

Reference groups were specified *before* observing validation outcomes:
- L: partyid='strong democrat'
- R: partyid='strong republican'

The response variables used to construct the poles exclude partyid and
polviews. Candidate pools included (a) the original 38 pole variables
and (b) all 574 eligible opinion-related model variables. With
categorical distributions, means cannot be assigned to answer labels.
The script saved full model-conditional distributions and used two
explicit descriptive reductions:

1. Marginal categorical modes. Result: 1 different-mode variable of
   the original 38, insufficient to define a reliable two-pole axis.
2. Conditional-excess contrast, retaining items with total variation
   >=0.05, fixed before evaluating the persona outcomes.

## Native model results

| Pole | Items | I(empty) | I(CM_core) | I(WF_core) | Independent polviews orientation |
|---|---:|---:|---:|---:|---|
| Existing manual 2018 v2 | 38 | +0.06005 | +0.07262 | +0.04441 | 12 concordant, 9 discordant, 0 ties |
| Model contrast from original 38 | 2 | +0.02123 | +0.02123 | +0.02123 | 0 concordant, 0 discordant, 21 ties |
| Model contrast from all 574 opinion items | 4 | +0.08092 | +0.27308 | -0.06828 | 5 concordant, 6 discordant, 10 ties |
| Direct native partyid-conditioned reference states | 1 anchored variable | -0.07617 | +0.99336 | -0.98023 | 14 concordant, 3 discordant, 4 ties |

Ordering compares the seven distinct categories of polviews in
their explicitly stated ideological order, using all 21 possible
comparisons. A tie receives half credit. These **are not independent
held-out respondents**: tests apply to different conditioning variables
of the same fitted model. They are independent of the pole-construction
criterion, not independent data.

The partyid-anchored poles obtain nearly maximal separation of the
example personas because partyid is among their conditioning variables.
This is circular as evidence of valid political measurement and is not
an acceptable replacement for response-derived reference poles.

The four-variable candidate produced opposite signs for CM and WF.
But its seven-category polviews ordering was **worse than the original
38-item pole**, and many labels were tied. Therefore **reject the
four-variable pole for production use**. Its exact CSV is preserved in
candidates/ for scientific reproducibility only.

The four variables in the candidate were:

| Variable | TV(P(.|Dem), P(.|Rep)) |
|---|---:|
| conpress | 0.149899 |
| confed | 0.143910 |
| gunlaw | 0.078919 |
| goveqinc | 0.055479 |

The other 570/574 candidate variables failed the prespecified
TV threshold or other response-contrast tests. The earlier
polviews-extreme conditioned experiment using the 38-item pool
yielded **zero** eligible contrasts at this threshold.

## Why the current 2018 ideology zero still warrants scrutiny

The original independent geometry audit showed the same 2018 model
under the original and revised hand-defined poles:

| Reference pole | I(empty) | I(CM_core) | I(WF_core) |
|---|---:|---:|---:|
| Original v1 | -0.03696 | -0.02811 | -0.04731 |
| Current v2, 38 items | +0.06005 | +0.07262 | +0.04441 |
| v2 restricted to 27 variables shared with 2024 | +0.00702 | +0.02491 | -0.01192 |

Both CM and WF are correctly *ordered* under all three definitions;
absolute signs depend heavily on the zero-point placement and
pole composition.

## Technical lessons

- Native GSS 2018 source-map labels are abbreviated, including
  polviews 'moderate', 'slghtly conservative', 'extrmly conservative',
  and partyid 'not str democrat', 'ind,near dem' and similar.
  The first scratch implementation recognized only 4/7 polviews and
  2/7 partyid labels. This was corrected, and all comparisons above
  use **all seven ordered categories**.
- The 2018 model conditional marginals change extremely little when
  conditioning on partyid alone. On the 38-variable manual-pole set,
  most conditional distributions are identical to reported precision;
  the largest differences were confed, gunlaw and natfare.
  This deserves an independent test against raw GSS data before
  attributing it to weak real-world ideological association.
- Individually taking categorical modes of a conditional marginal
  distribution does not create a joint-typical respondent.
  The model's conditional distribution should not be conflated with
  a survey-weighted empirical stratum profile.
- Selecting a pole solely because CM and WF have opposite signs
  would invalidate the external orientation test.

## Decision and next experiment

**Do not change canonical 2018 poles on the evidence so far.**

The next proper analysis should use raw GSS 2018 responses and weights:
partition development and evaluation respondents, estimate the
distribution of answers by ideology/affiliation strata with stated
sampling design, define response-population medoids (or robust
probabilistic prototypes), and evaluate ordered-category monotonicity
and neutral reference calibration in held-out respondents.

The repo intentionally does not distribute raw GSS microdata
(data/raw/README.md). Until those data are supplied, this work is
reproducible model-conditional evidence, not an empirical survey-based
re-estimation of the ideology axis.
