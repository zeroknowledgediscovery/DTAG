# Question optimization with DTAG: ideology poles, personas and question sequences

This document records the analysis carried out on the `dev` branch to find survey-question
sequences that move simulated respondents' ideology in chosen directions, from the first check
of the ideology sign to the validated polarization and depolarization sets. It concerns the
native DTAG model and ideology index only; the DTAG web application is described separately
(`webapp/README.md`).

Everything here uses the native GSS LSM models (mainly GSS 2024) and the CM / WF personas:

- **CM** (`gss2024_cm`): *45 year old white male with children in rural Alabama, regular news
  consumer, working in farming, veteran, conservative.*
- **WF** (`gss2024_wf`): *22 year old white female without children in urban New York, regular
  news consumer, working in retail, highly progressive.*

Outputs live in `assets/polar_vectors/` (poles), `assets/question_sets/optimized/`,
`assets/question_sets/polarization/` and `assets/question_sets/depolarization/`; the search
and validation code is `scripts/optimize_question_sets.py`.

## Contents

1. [The ideology index](#1-the-ideology-index)
2. [Why the conservative persona scored negative](#2-why-the-conservative-persona-scored-negative)
3. [Wave-specific poles: fixing label mismatches](#3-wave-specific-poles-fixing-label-mismatches)
4. [Revising the right pole (v2)](#4-revising-the-right-pole-v2)
5. [First question optimization: modal answers](#5-first-question-optimization-modal-answers)
6. [Robust optimization: sampled answers and perturbed personas](#6-robust-optimization-sampled-answers-and-perturbed-personas)
7. [The polarizing set](#7-the-polarizing-set)
8. [A validation bug and its correction](#8-a-validation-bug-and-its-correction)
9. [The depolarizing set](#9-the-depolarizing-set)
10. [Findings](#10-findings)
11. [Using the sets in a real survey](#11-using-the-sets-in-a-real-survey)
12. [Reproduction and file index](#12-reproduction-and-file-index)

---

## 1. The ideology index

For a respondent state *s* (the survey answers assigned so far, with everything else inferred by
the native model), DTAG computes

> I(s) = ( d(s_L, s) − d(s_R, s) ) / d(s_L, s_R)

where *d* is the native qdistance between model states and *s_L*, *s_R* are the states built
from the left and right **pole** answers (`assets/polar_vectors/polar_vectors.csv`, a list of
GSS items with a liberal and a conservative answer each). I(s_L) = −1 and I(s_R) = +1; I = 0 means
equidistant from the two poles, **not** "average respondent".

In a session, the persona text is turned into initial survey assignments, and each question is
mapped to survey items whose answer (modal, `max`, or sampled, `draw`) can be written into the
state ("state updates"). The ideology trajectory is I after each question.

## 2. Why the conservative persona scored negative

**Question:** the conservative persona started with a negative ideology, the opposite of the
intended convention.

**What we found** (GSS 2014–2024, checked directly against the models, without the web app):

- The ordering was always right: CM > the model's average respondent > WF.
- But the **average respondent (empty state) sat below zero in every wave** (e.g. 2024:
  −0.138), so a persona that fixes only a handful of ~800 variables stayed negative.
- The average respondent was nearer the L pole than the R pole (2024: d_L = 0.018 vs
  d_R = 0.024): the right pole was further from the population.
- Leave-one-out analysis showed which pole items pulled the average negative: mainly R answers
  that few respondents give, even among conservatives (e.g. "too much" spending on Social
  Security, "no" to abortion when the mother's health is endangered).

## 3. Wave-specific poles: fixing label mismatches

Before changing any poles, every pole answer was checked against each wave's native model
labels. Many did not match: wording changed across waves ("legal" vs "should be legal",
"book of fables" vs "ancient book", "strongly disagree" vs "strong disagree"), the 2021
split-ballot items have two versions, some items were not asked, and one pole entry was a
source error (`colmil` R was "not fired", a `colcom` label).

Unmatched answers were silently ignored until then. The fix (commit on `dev`, documented in
`assets/polar_vectors/README.md`):

- `assets/polar_vectors/gss_pole_corrections.csv` lists every label correction with its reason.
- `scripts/build_gss_polar_vectors.py` resolves the canonical poles against each of the 35 GSS
  waves and writes `assets/polar_vectors/gss/gss_YYYY_polar_vectors.csv` plus a full
  item × wave report. An item is kept only if **both** its L and R answers exist in that wave;
  otherwise it is dropped from both poles and reported, never written.
- At runtime DTAG switches to the wave's file automatically and validates every pole pair
  against the loaded model; dropped items appear in the run metadata.

The poles stay the same across years except for these phrasing corrections.

## 4. Revising the right pole (v2)

The right pole was then made more representative with **one rule applied once, identically
in every wave**:

> A right-pole answer given by fewer than 15% of respondents (model marginal, averaged over
> GSS 2014–2024) moves one step toward the centre of its answer scale, never past the middle;
> if no such answer exists (yes/no items), the item is dropped from both poles.

| Item | R (v1) | R (v2) |
|---|---|---|
| `natsoc`, `natenvir` | too much | about right |
| `pillok`, `pilloky`, `religcon`, `religint` | strongly disagree | disagree |
| `abhlth` | no | dropped from both poles |

The left pole is unchanged; v1 is kept as `polar_vectors_v1.csv`. Effect (average respondent /
CM / WF):

| Wave | v1 | v2 |
|---|---|---|
| 2014 | −0.117 / −0.058 / −0.192 | −0.039 / +0.017 / −0.126 |
| 2016 | −0.060 / −0.031 / −0.123 | +0.046 / +0.063 / −0.031 |
| 2018 | −0.057 / −0.045 / −0.083 | +0.060 / +0.071 / +0.027 |
| 2022 | −0.193 / −0.091 / −0.270 | −0.100 / −0.001 / −0.196 |
| 2024 | −0.138 / −0.054 / −0.251 | −0.052 / +0.020 / −0.196 |

A stricter 20% threshold was tested and rejected (it made WF positive in two waves). All later
work uses v2.

**A finding that shaped everything after:** conditioning the model on "extremely conservative
+ strong Republican" vs "extremely liberal + strong Democrat" barely changed its answer
distributions on the pole items. Persona answers propagate weakly through the model, which is
why CM and WF start close together.

## 5. First question optimization: modal answers

**Goal:** sequences that move CM and WF (1) in the same direction, (2) in opposite directions,
(3) WF up and CM down, (4) CM up and WF down.

**Set-up** (results in `assets/question_sets/optimized/`):

- GSS 2024, v2 poles, state updates on, **modal answers (`max`)**, so each run is deterministic.
- Personas hand-coded from the stated facts of the two descriptions (sex, age, race, region,
  children, place size, news habit, work status, veteran status, political views).
- Each question = one survey item, written in plain English from the GSS wording.
- **Opinion items only.** A first run picked items such as religious preference, past vote,
  sex at birth or gun ownership; asking those would overwrite the persona's identity. The
  candidate set was reduced to 223 opinion items by excluding respondent facts, identity,
  household facts, behaviour logs, interviewer vignettes, survey meta-data, party and
  left–right self-placement, and duplicate split-ballot versions of an item.
- Greedy search: at each step add the item with the best worse-of-the-two move; stop when the
  next step would move either index by less than 0.001.

**Results:**

| Goal | Questions | CM change | WF change |
|---|---:|---:|---:|
| Both up | 12 | +0.222 | +0.227 |
| Both down | 12 | −0.417 | −0.374 |
| CM up, WF down (net over the set) | 12 | +0.222 | −0.225 |
| CM up, WF down (every step) | 4 | +0.110 | −0.237 |
| WF up, CM down (net) | 12 | −0.015 | +0.015 |

The model answered almost every item identically for both personas, so "same direction" was
easy. Only religiosity items, defence spending, reparations and aid to Black Americans
separated them, always with CM answering conservatively; that made CM-up/WF-down possible and
WF-up/CM-down essentially impossible (±0.015 is a limit case).

These are single deterministic runs: no answer sampling, no persona variation, no confidence
intervals.

## 6. Robust optimization: sampled answers and perturbed personas

**Goal:** 10–12 questions that, with state updates and **sampled answers (`draw`)**, robustly
move CM right and WF left at the same time, with confidence intervals, robust to perturbations
of the starting persona, for validation in real surveys.

### Persona perturbation

Each persona became a distribution of starting states (`sample_persona` in the script): age,
children, place size, news habit, work status, veteran years and strength of political views
vary; each stated fact is dropped with probability 0.15 (the LLM may not assign it); inferences
an LLM might add (party, religion, attendance, marital status, education) are added with
probability 0.4. Search and validation use disjoint seeds.

### What did not work, and why

1. **Step-wise expected change.** Scoring each question by the lower quartile of its expected
   change across perturbed personas, and requiring every step to help both, stopped after one
   question ("how often do you pray").
2. **Net expected change.** Relaxing to the set's net change still stopped after one question.
   Under sampling, "pray" is a lottery: for WF about 30% of answers ("never") pull the index far
   down and 70% push it slightly up, so the mean helps but most individual runs go the wrong
   way. Expected values hide that.
3. **Mean / spread of the sampled outcome.** Scoring each candidate by the full outcome
   distribution (perturbed persona × sampled answer) and maximizing the worse persona's
   mean / standard deviation still found nothing beyond "pray".

**Root cause, measured directly:** with only the stated facts, the model gives CM and WF
essentially the same answer distribution on almost every opinion item (median total-variation
distance 0.000; only 9 of 222 items above 0.1). Sampling cannot pull apart two respondents who
answer the same way.

**Rich personas.** Adding the usual inferences (CM: strong Republican, Protestant, attends every
week, married, high school; WF: strong Democrat, no religion, never attends, never married,
bachelor's) separates them: 29 items above 0.1, religious-activity items up to 0.73, and the
starting gap doubles. This matches how a real survey would select the comparison groups, so all
later work uses `--rich` (each inference kept with probability 0.8 in perturbed variants).

### Search procedure that worked

- **Greedy search** under the mean/spread criterion with rich personas, forced to 12 questions,
  re-screening all 222 opinion items every two steps. Its held-out validation moved WF but not
  CM (CM +0.000 [−0.001, +0.001]).
- **Local search over whole sequences:** replace one question at a time from a candidate pool
  and keep the swap if it raises min(t_CM, t_WF), where *t* is the mean signed change divided by
  its standard error over 60 simulated runs per persona. Every candidate set is evaluated on the
  same personas and seeds (common random numbers), separate from the validation seeds.
- **Validation** on held-out personas and seeds: 300 runs per persona (block 1, seeds from
  100000) and 400 runs per persona (block 2, seeds from 300000, never used for any decision),
  with 20 random 12-item opinion sequences as a baseline and earlier sets as comparisons.
  Results are reported for every prefix length 1–12, so the best 10–12 length is chosen on
  validation data.

## 7. The polarizing set

`assets/question_sets/polarization/` — recommended **first 10 questions**: prayer frequency,
abortion when a family cannot afford more children, the Bible, Republican Party rating, defence
spending, reparations, church activities, Nikki Haley rating, Social Security spending, police
striking a verbally abusive citizen.

| 10 questions | CM → right | WF → left | Gap widens |
|---|---|---|---|
| Block 1 (300 runs) | +0.019 [+0.008, +0.029] | −0.014 [−0.027, −0.003] | +0.033 [+0.017, +0.049] |
| Block 2, untouched (400) | +0.012 [+0.003, +0.021] | −0.016 [−0.027, −0.006] | +0.028 [+0.013, +0.042] |

Both personas move significantly in the intended direction on both blocks. The 12-question
version moves WF further but loses CM's significance on block 2, so 10 is recommended. Random
12-item sets move both personas together (median gap change −0.003). An independently drawn
CM run and WF run both move as intended about 30% of the time.

## 8. A validation bug and its correction

While validating the depolarizing set, its gap confidence interval came out implausibly narrow.
Cause: in validation, the CM run and the WF run with the same index used **the same
answer-sampling random stream**, so on items where the two personas have similar
distributions they tended to draw the same answers. Per-persona means and CIs were unaffected,
but the gap CI computed from these paired runs was about half as wide as it should be for two
independent groups, and the "both moved as intended" share was distorted (reported as 15% for
the polarizing set instead of ~30%).

Fix (`scripts/optimize_question_sets.py`): the personas now get independent sampling streams,
the gap CI resamples the two groups separately (as for two independent survey samples), and
"both as intended" is P(CM as intended) × P(WF as intended). The polarization numbers above and
in its README were recomputed from the saved trajectories (`corrected_summary.json`); the
conclusions did not change.

## 9. The depolarizing set

`assets/question_sets/depolarization/` — same pipeline with `--goal depolarize` (CM toward the
L pole, WF toward the R pole). 12 questions: welfare spending, abortion for any reason, a Muslim
clergyman who preaches hatred of the US teaching in college, belief in God, Trump rating, birth
control for teenagers without parental approval, Black people working their way up without
special favors, death penalty, sex education, confidence in medicine, Harris rating, an
anti-religionist speaking in your community.

| 12 questions | CM → left | WF → right | Gap closes |
|---|---|---|---|
| **Pooled (700 runs each)** | **−0.020** [−0.028, −0.011] | **+0.020** [+0.012, +0.028] | **−0.040** [−0.051, −0.028] |
| Block 2, untouched (400) | −0.026 [−0.037, −0.015] | +0.018 [+0.007, +0.028] | −0.044 [−0.059, −0.029] |
| Block 1 (300) | −0.012 [−0.024, +0.001] | +0.022 [+0.009, +0.036] | −0.034 [−0.053, −0.016] |

The gap closes by about a quarter of the average starting gap (0.159). On the untouched block
both personas move significantly for every length from 6 to 12. Most random 12-item sets leave
the gap unchanged (median −0.001), but 2 of 20 closed it by 0.03 or more, mostly by moving one
persona: part of the effect is generic, because sampling answers pulls each persona toward the
population on items where its own answers are uncertain (abortion is the biggest single lever).

## 10. Findings

1. **Pole definition matters as much as the personas.** Unmatched labels were silently ignored
   and some R answers were held by very few respondents, which put the average respondent and
   the conservative persona on the liberal side. Wave-specific poles and the v2 right pole fixed
   the sign without changing poles from year to year beyond phrasing.
2. **Persona answers propagate weakly.** With only the facts stated in a short description, the
   model treats a conservative and a progressive almost identically on opinion items. Party,
   religion and religious attendance are what separate them; persona descriptions should state
   them.
3. **Modal-answer optimization is misleading for real-survey design.** Deterministic runs gave
   large, clean effects (±0.2–0.4 for same-direction sets), but they hide answer variation.
4. **Under sampled answers, effects are population-level.** Both validated sets move group means
   in the intended directions (|change| ≈ 0.01–0.03 per persona, gap ≈ 0.03–0.04) with CIs
   excluding zero, but a single run's change has an SD of about 0.1, and an independent
   conservative/progressive pair both moves as intended only ~25–30% of the time.
5. **Validate on held-out data.** Search-time estimates were optimistic; a 12-question set that
   looked best on one block lost significance for CM on an untouched block.
6. **Compare with random sets.** Random question sets mostly move both personas together; a few
   can widen or close the gap by chance on small samples, which is why each claimed effect is
   reported with its own CI and the random distribution.

## 11. Using the sets in a real survey

- Compare **group means** (conservative vs progressive respondents, before vs after the question
  block), not individual respondents. Effects of 0.01–0.04 index units with per-respondent SD
  ≈ 0.1 need hundreds of respondents per group.
- Use persona descriptions that state party, religion and attendance. Descriptions that decode to
  the validated base states:
  - **CM:** *45-year-old white man living in open country outside a small town in rural Alabama,
    in the South. He is married and has two children. He works full time in farming. He is a
    veteran who served 2 to 4 years of active duty in the armed forces. He reads a newspaper
    every day. His education ended with a high school diploma; he did not attend college. He
    thinks of himself as conservative and is a strong Republican. He is Protestant and attends
    religious services every week.*
  - **WF:** *22-year-old white woman living in New York City, a large central city in the
    Northeast. She has never been married and has no children. She works full time in retail.
    She has never served in the armed forces. She reads a newspaper every day. She has a
    bachelor's degree. She thinks of herself as extremely liberal and is a strong Democrat. She
    has no religion and never attends religious services.*
- Keep the question order (answers carry forward).
- In DTAG, check each answer's *Model evidence*: the numbers assume one survey item per
  question, and with a real LLM extra related items may be selected.
- All results are for GSS 2024 with the v2 poles; other waves need re-optimizing.

## 12. Reproduction and file index

**Search and validate** (`python scripts/optimize_question_sets.py --help` for all options):

```bash
# greedy search, then local search from its result, then validation on a fresh seed block
python scripts/optimize_question_sets.py --goal polarize --rich --force-length --out outputs/pol_greedy --baselines 0
python scripts/optimize_question_sets.py --goal polarize --rich --out outputs/pol_ls \
  --local-search <greedy sequence> --pool <candidate items> --budget 40 --ls-n 60 --baselines 0
python scripts/optimize_question_sets.py --goal polarize --rich --out outputs/pol_check \
  --sequence <final sequence> --val-seed 300000 --n-val 400 --baselines 20
```

Use `--goal depolarize` for the depolarizing direction. Each folder's README has the exact
commands for its set. Runs take 1–4 hours on 4 cores.

**Poles**

| Path | Contents |
|---|---|
| `assets/polar_vectors/polar_vectors.csv` | canonical poles (v2) |
| `assets/polar_vectors/polar_vectors_v1.csv` | original poles |
| `assets/polar_vectors/gss_pole_corrections.csv` | documented label corrections |
| `assets/polar_vectors/gss/` | 35 wave-specific pole files and the resolution report |
| `scripts/build_gss_polar_vectors.py`, `scripts/polar_vectors.py` | builder and resolver |

**Question sets**

| Path | Contents |
|---|---|
| `assets/question_sets/optimized/` | modal-answer sets for the four direction goals (§5) |
| `assets/question_sets/polarization/` | validated polarizing set, 10 and 12 questions (§7) |
| `assets/question_sets/depolarization/` | validated depolarizing set, 12 questions (§9) |
| `scripts/optimize_question_sets.py` | persona perturbation, opinion-item filter, search, validation |

Each validated folder contains the question CSV(s) (`step,question`, uploadable with *Run
sequence…*), a README, `corrected_summary.json` (per-length results with independent-group CIs),
the validation JSON files and the raw validation trajectories (`*_trajectories.npz`).
