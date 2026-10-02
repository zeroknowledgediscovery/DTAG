# Polarizing question set, GSS 2024 (state updates on, sampled answers)

A question sequence that, asked in order to both personas with **state updates on** and
**`draw`** (answers sampled from the native conditional distribution), moves the conservative
persona (CM) toward the R pole and the progressive persona (WF) toward the L pole at the same
time, validated with confidence intervals on held-out, perturbed personas.

**Recommended: `gss2024_polarize_cm_wf_draw_10.csv`** (10 questions). The 12-question version
is kept for reference; its extra two questions move WF further but cost CM its significance on
fresh data. The table below (and `sequence` in the validation JSON) maps each step to its GSS 2024 item.

| Step | Item | Question (short) |
|---:|---|---|
| 1 | `pray` | How often do you pray? |
| 2 | `abpoor` | Legal abortion if the family has a very low income and can't afford more children? |
| 3 | `bible` | Feelings about the Bible (word of God / inspired word / ancient book) |
| 4 | `raterepp` | Rate the Republican Party, 0–100 |
| 5 | `natarms` | Spending on the military, armaments and defense |
| 6 | `dsndntpay` | Reparations for descendants of enslaved people? |
| 7 | `relactiv` | How often do you take part in church activities (besides services)? |
| 8 | `ratechall324` | Rate Nikki Haley, 0–100 |
| 9 | `natsoc` | Spending on Social Security |
| 10 | `polabuse` | Approve of a policeman striking a citizen who was verbally abusive? |
| (11) | `rateincumb24` | Rate Joe Biden, 0–100 |
| (12) | `corruptn` | How widespread is corruption in the public service? |

## Results (change in ideology index from the start; mean and 95% bootstrap CI)

Each run: a perturbed persona, the questions in order, every answer sampled and written into
the state. Two disjoint validation blocks, never used in the search.

| Set | Block (runs per persona) | CM → right | WF → left | Gap widens | Both as intended* |
|---|---|---|---|---|---:|
| **10 questions** | 1 (300) | **+0.019** [+0.008, +0.029], 61% up | **−0.014** [−0.027, −0.003], 48% down | **+0.033** [+0.017, +0.049] | 29% |
| **10 questions** | 2, untouched (400) | **+0.012** [+0.003, +0.021], 58% up | **−0.016** [−0.027, −0.006], 51% down | **+0.028** [+0.013, +0.042] | 30% |
| 12 questions | 1 (300) | +0.014 [+0.004, +0.024] | −0.020 [−0.031, −0.008] | +0.034 [+0.018, +0.049] | 30% |
| 12 questions | 2, untouched (400) | +0.006 [−0.003, +0.015] | −0.022 [−0.034, −0.011] | +0.028 [+0.014, +0.043] | 30% |
| Greedy search (earlier) | 1 (300) | +0.000 [−0.001, +0.001] | −0.006 [−0.008, −0.005] | +0.006 [+0.004, +0.008] | 38% |
| Deterministic set v1 (`../optimized/`) | 1 (300) | +0.019 [+0.007, +0.030] | −0.004 [−0.017, +0.009] | +0.023 [+0.006, +0.040]† | 28% |
| 20 random 12-item sets | 30 each | means −0.078 … +0.030 | means −0.058 … +0.028 | median −0.003, max +0.030 | — |

\* Probability that an independently drawn conservative run and progressive run both move the
intended way (product of the two shares). † Normal approximation from the per-persona CIs
(trajectories not kept).

**Correction (2026-10-02).** The first version of this table computed the gap CI and the "both"
share from runs paired by index, and those pairs shared one answer-sampling stream, so CM and WF
tended to draw the same answers. That made the gap CIs about half as wide as they should be and
the "both" share too low (15%). The numbers above treat the two groups as independent samples,
as in a real survey; the per-persona means and CIs were not affected. `corrected_summary.json`
has the corrected per-length results; the `gap_change` and `share_both` fields in the other JSON
files predate this correction. The script now samples the two personas independently.

Per-length results (1–12 questions) are in `validation_block1.json` and
`validation_block2_fresh.json` (`optimized.per_length`; gap and "both" corrected in
`corrected_summary.json`); the raw trajectories are in the `*_trajectories.npz` files. Both personas move significantly on
both blocks for the first 2, 3, and 7–10 questions (block 1 also 11–12; block 2 also 5–6).

## How to read this

- **As a population effect it is robust:** averaged over respondents like these, the 10
  questions move conservatives right and progressives left, with both CIs excluding zero on
  two independent validation blocks, and widen the gap by about 0.03 [≈0.015, 0.045] (random
  question sets move both personas together, median gap change −0.003).
- **For a single respondent it is not:** CM moves right in ~60% of runs and WF left in ~50%;
  an independently drawn pair both moves the intended way only ~30% of the time. Answer sampling dominates individual
  trajectories. A real-survey validation should compare **group means** (conservative vs
  progressive respondents, before vs after the question block), not individual respondents,
  and needs samples in the hundreds per group for effects of this size (≈0.01–0.02 index
  units; SD of a single run ≈ 0.09–0.11).
- **Effect sizes are small** relative to the starting gap between the personas (≈0.25).

## Method

- Model: native GSS 2024 LSM; ideology poles `assets/polar_vectors/gss/gss_2024_polar_vectors.csv`
  (v2 right pole). One survey item per question; answers sampled (`draw`); each answer written
  into the respondent state before the next question.
- Personas (`--rich`): the stated facts of `gss2024_cm` / `gss2024_wf` plus the inferences an
  LLM usually adds (party, religion, attendance, marital status, education). Perturbations vary
  age, children, place size, news habit, veteran years and strength of political views, drop
  each stated fact with probability 0.15, and keep each inference with probability 0.8 (with
  varied values). With the stated facts only, the model gives the two personas nearly identical
  answer distributions (median total-variation distance 0.000 over 222 opinion items) and no
  robust polarizing set exists; the inferences are what separate them.
- Candidates: GSS 2024 opinion items only (no respondent facts, identity, or party/left–right
  self-placement).
- Search: a greedy search on exact per-question outcome distributions, then a local search over
  whole 12-question sets maximizing min(t_CM, t_WF) of the signed change (60 runs per persona,
  common random numbers, seed block 50000), starting from the questions of the two earlier sets
  that separate the personas. Validation blocks start at seeds 100000 and 300000.

## Caveats

- Assumes each question maps to its single intended item. With a real LLM, DTAG may select
  additional related items; check *Model evidence* in the web app.
- Persona states in the app come from the LLM's reading of the persona text; the perturbation
  model above is an approximation of that variation.
- Order matters (answers carry forward). Specific to GSS 2024 and the v2 poles.

## Reproduce

```bash
python scripts/optimize_question_sets.py --rich --out outputs/polarization_check \
  --sequence pray,abpoor,bible,raterepp,natarms,dsndntpay,relactiv,ratechall324,natsoc,polabuse \
  --val-seed 300000 --n-val 400 --baselines 0
```

`python scripts/optimize_question_sets.py --help` lists the search options (greedy search,
`--local-search`, baselines, comparison sets).
