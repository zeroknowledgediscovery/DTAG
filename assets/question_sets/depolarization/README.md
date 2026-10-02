# Depolarizing question set, GSS 2024 (state updates on, sampled answers)

A 12-question sequence that, asked in order to both personas with **state updates on** and
**`draw`** (answers sampled from the native conditional distribution), moves the conservative
persona (CM) toward the L pole and the progressive persona (WF) toward the R pole, i.e. toward
each other, validated with confidence intervals on held-out, perturbed personas.

**File: `gss2024_depolarize_cm_wf_draw_12.csv`** (upload with *Run sequence…*; in two-respondent
mode set the target to *Both*).

| Step | Item | Question (short) |
|---:|---|---|
| 1 | `natfare` | Spending on welfare |
| 2 | `abany` | Legal abortion if the woman wants it for any reason? |
| 3 | `colmslm` | Allow a Muslim clergyman who preaches hatred of the US to teach in college? |
| 4 | `god` | Belief about God (don't believe … know God exists) |
| 5 | `ratechall124` | Rate Donald Trump, 0–100 |
| 6 | `pillok` | Birth control for teenagers 14–16 without parental approval? |
| 7 | `wrkwayup` | Black people should work their way up without special favors? |
| 8 | `cappun` | Death penalty for murder? |
| 9 | `sexeduc` | Sex education in public schools? |
| 10 | `conmedic` | Confidence in medicine |
| 11 | `ratechall224` | Rate Kamala Harris, 0–100 |
| 12 | `spkath` | Allow an anti-religionist to speak in your community? |

## Results (change in ideology index; mean and 95% bootstrap CI)

Each run: a perturbed persona, the 12 questions in order, every answer sampled and written into
the state. Neither validation block was used in the search (search seeds start at 50000), so
they are pooled as well. Average starting point: CM +0.023, WF −0.137 (gap 0.159).

| Set | Validation (runs per persona) | CM → left (−) | WF → right (+) | Gap closes (−) | Both as intended* |
|---|---|---|---|---|---:|
| **12 questions** | **pooled (700)** | **−0.020** [−0.028, −0.011], 61% | **+0.020** [+0.012, +0.028], 43% | **−0.040** [−0.051, −0.028] | 26% |
| 12 questions | block 1 (300) | −0.012 [−0.024, +0.001], 57% | +0.022 [+0.009, +0.036], 46% | −0.034 [−0.053, −0.016] | 26% |
| 12 questions | block 2, untouched (400) | −0.026 [−0.037, −0.015], 64% | +0.018 [+0.007, +0.028], 41% | −0.044 [−0.059, −0.029] | 26% |
| 10 questions (first 10) | pooled (700) | −0.015 [−0.023, −0.006], 61% | +0.025 [+0.016, +0.034], 42% | −0.039 [−0.051, −0.027] | 25% |
| Greedy search (start of the local search) | block 1 (300) | −0.004 [−0.016, +0.008] | +0.029 [+0.018, +0.042] | −0.034 [−0.052, −0.016] | 26% |
| Greedy search | block 2 (400) | −0.018 [−0.029, −0.007] | +0.026 [+0.015, +0.036] | −0.043 [−0.059, −0.028] | 27% |
| 20 random 12-item opinion sets | block 2 seeds, 30 each | means −0.059 … +0.013 | means −0.019 … +0.016 | median −0.001; 2 of 20 below −0.03 | median 24% |

\* Probability that an independently drawn conservative run and progressive run both move the
intended way (product of the two shares). Percentages after the CIs: share of runs moving in
the intended direction.

Per-length results (1–12 questions) for every block, pooled and for the greedy set are in
`corrected_summary.json`; raw trajectories in the `*_trajectories.npz` files.

## How to read this

- **As a population effect it is robust:** pooled over 700 held-out runs per persona, the 12
  questions move conservatives left and progressives right by about 0.02 each and close the gap
  by 0.040 [0.028, 0.051], about a quarter of the average starting gap. WF moves significantly
  on both blocks; CM is significant on the untouched block and pooled, borderline on block 1.
- **It is not a strong individual-level effect:** CM moves left in ~61% of runs, WF moves right
  in only ~43% (WF's mean shift comes from a minority of runs with large moves); an independent
  pair both moves the intended way ~26% of the time, close to random question sets (24%).
  The SD of a single run's change is ≈0.11, five times the mean shift.
- **Compared with random question sets:** most random sets leave the gap where it is (median
  −0.001), but a few close it by 0.03–0.06 on their 30-run estimates, mostly by moving one
  persona; this set closes it by 0.040 with both personas moving. Part of the effect is generic:
  sampling answers pulls each persona toward the population on items where its own answers are
  not certain (abortion, item 2, is the largest single lever and also appears in the best
  random set).
- **Comparison with polarization:** the polarizing set (`../polarization/`) widens the gap by
  about 0.03; this set narrows it by about 0.04. Both are population-mean effects of similar
  size, and both need hundreds of respondents per group to detect in a real survey.

## Method

Same pipeline as `../polarization/`, with `--goal depolarize`:

- Model: native GSS 2024 LSM; ideology poles `assets/polar_vectors/gss/gss_2024_polar_vectors.csv`
  (v2 right pole). One survey item per question; answers sampled (`draw`) and written into the
  respondent state before the next question.
- Personas (`--rich`): the stated facts of `gss2024_cm` / `gss2024_wf` plus party, religion,
  attendance, marital status and education, with perturbations (age, children, place size,
  news habit, veteran years, strength of political views; stated facts dropped with probability
  0.15; inferences kept with probability 0.8). Persona descriptions that decode to the base
  state are given below.
- Candidates: GSS 2024 opinion items only (no respondent facts, identity, or party/left–right
  self-placement).
- Search: greedy search on exact per-question outcome distributions (16 states per persona,
  full re-screen every 2 steps, 12 questions forced), then a local search over whole sequences
  (40 single-question swaps from a pool of the screens' top items, 60 runs per persona per
  evaluation, common random numbers) maximizing min(t_CM, t_WF) of the signed change.
- Validation: block 1 (seeds from 100000, 300 runs per persona) and block 2 (seeds from 300000,
  400 runs per persona, never used before), CM and WF sampled independently; gap CI from separate
  bootstraps of the two groups; 20 random 12-item opinion sequences as a baseline.

Persona descriptions that, decoded correctly, give the base rich states:

- CM: *45-year-old white man living in open country outside a small town in rural Alabama, in the
  South. He is married and has two children. He works full time in farming. He is a veteran who
  served 2 to 4 years of active duty in the armed forces. He reads a newspaper every day. His
  education ended with a high school diploma; he did not attend college. He thinks of himself as
  conservative and is a strong Republican. He is Protestant and attends religious services every
  week.*
- WF: *22-year-old white woman living in New York City, a large central city in the Northeast.
  She has never been married and has no children. She works full time in retail. She has never
  served in the armed forces. She reads a newspaper every day. She has a bachelor's degree. She
  thinks of herself as extremely liberal and is a strong Democrat. She has no religion and never
  attends religious services.*

## Caveats

- Assumes each question maps to its single intended item; with a real LLM, DTAG may select
  additional related items (check *Model evidence* in the web app).
- In the app, the starting state comes from the LLM's reading of the persona text; check
  *Initial state* for party, religion and attendance, which drive the separation.
- Order matters (answers carry forward). Specific to GSS 2024 and the v2 poles.
- `validation_block1.json` was written before the independent-groups correction; its
  `gap_change` and `share_both` fields are superseded by `corrected_summary.json`.

## Reproduce

```bash
# search (about 4 h on 4 cores): greedy, then local search from its result
python scripts/optimize_question_sets.py --goal depolarize --rich --force-length --out outputs/dep_greedy --baselines 0
python scripts/optimize_question_sets.py --goal depolarize --rich --out outputs/dep_ls \
  --local-search natfare,abany,colmslm,god,ratechall124,pillok,obey,cappun,popular,conmedic,ratechall224,conbus \
  --pool "$(python -c "import json;d=json.load(open('outputs/dep_greedy/search.json'));print(','.join(dict.fromkeys([c['variable'] for c in d['chosen']]+[t['variable'] for s in d['screens'] for t in s['top'][:30]])))")" \
  --budget 40 --ls-n 60 --baselines 0
# validate the final set on a fresh block
python scripts/optimize_question_sets.py --goal depolarize --rich --out outputs/dep_check \
  --sequence natfare,abany,colmslm,god,ratechall124,pillok,wrkwayup,cappun,sexeduc,conmedic,ratechall224,spkath \
  --val-seed 300000 --n-val 400 --baselines 20 --n-base 30
```
