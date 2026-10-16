# Experiment: pushing CM and WF left and right with greedy question selection

Native GSS 2018 LSM, the original 38-item 2018 poles (unchanged), and the centered index
J(s) = I(s) − I(∅), where I(∅) = +0.0600465. J > 0 means the persona is closer to the right pole than the empty state is.
Run on branch `dev-claude`.

## Setup

**Personas.** The committed rich reference states (`assets/question_sets/personas/target_states.json`),
keeping only the assignments valid for the 2018 model:

- CM (8 facts), J₀ = **+0.0263**
- WF (7 facts), J₀ = **−0.0358**
- The CM−WF gap is 0.062.

**Policies.** Each run has 6 steps. At every step a question is asked, and the answer is drawn from the
native P(a | sₜ, v). The asker never chooses the answer. The state is then updated.

- **greedy_mu.** Re-score all candidate questions exactly at the current state sₜ
  (`optimizer.one_step_geometry`). Ask argmax μ to push right, or argmin μ to push left, where
  μ_v = Σₐ P(a|sₜ,v)·Δ_v(a|sₜ). 3 sampled runs per case.
- **random.** Ask a uniformly random candidate question. 30 runs per case. This is the baseline.

**Candidates.** Non-pole questions only, so a push never writes directly into the pole definition.
To keep each step to about 1 minute, the candidates are restricted to a 120-question pool: the
items with the largest |μ| or range in the exact step-0 sweep. Audit: at the final state of greedy
run 0 in each case, a full sweep over all ~982 non-pole questions picked a question inside the pool
(CM→right `coeduc`, CM→left `abhlth`, WF→right `heaven`, WF→left `HUNT1`), so the pool restriction
did not change that choice.

**Reproduce one case.** Run `python scratch/gss2018_pole_geometry/greedy_push_runs.py --persona CM --direction right --n-items 6 --audit`
(about 20–25 min on 4 cores; seeded; a local CM→right run reproduced these numbers exactly). `--n-items` sets the run length.

## Start and end values

| Case | J start | Greedy J end (3 runs) | Greedy mean end | Random mean end (30) [95% CI] | Random min / max end |
|---|---:|---|---:|---:|---|
| CM → right | +0.0263 | +0.0855, +0.0189, +0.0025 | **+0.0356** | +0.0183 [+0.0114, +0.0253] | −0.0196 / +0.0532 |
| CM → left | +0.0263 | +0.0184, −0.0108, +0.0255 | **+0.0110** | +0.0212 [+0.0141, +0.0280] | −0.0172 / +0.0616 |
| WF → right | −0.0358 | +0.0447, −0.0195, −0.0299 | **−0.0016** | −0.0349 [−0.0428, −0.0269] | −0.0847 / +0.0160 |
| WF → left | −0.0358 | −0.0600, −0.0598, −0.0968 | **−0.0722** | −0.0266 [−0.0358, −0.0177] | −0.0683 / +0.0184 |

## Change in J (end − start)

| Case | Greedy runs ΔJ | Greedy mean ΔJ | Random mean ΔJ [95% CI] | Greedy − random | Runs in the intended direction | Steps on one-sided questions |
|---|---|---:|---:|---:|---:|---:|
| CM → right | +0.0591, −0.0074, −0.0238 | +0.0093 | −0.0081 [−0.0149, −0.0010] | +0.0174 | 1 / 3 | 2 / 18 |
| CM → left | −0.0080, −0.0371, −0.0008 | −0.0153 | −0.0051 [−0.0122, +0.0017] | −0.0102 | 3 / 3 | 10 / 18 |
| WF → right | +0.0804, +0.0163, +0.0059 | +0.0342 | +0.0009 [−0.0071, +0.0089] | +0.0333 | 3 / 3 | 3 / 18 |
| WF → left | −0.0242, −0.0240, −0.0610 | −0.0364 | +0.0092 [+0.0000, +0.0181] | −0.0456 | 3 / 3 | 4 / 18 |

Random-run seeds differ between the left and right cases, so the random baselines for one persona differ by direction.

## Findings

1. **On average, greedy question selection moves both personas in the requested direction,
   and further than random questions do, in all four cases.** In each case the greedy mean
   falls outside the random baseline's 95% CI. The effect is about 0.01–0.05 in J, against a
   CM−WF gap of 0.062.
2. **Pushing a persona further toward its own side works more reliably than pushing it across.**
   - WF → left: all 3 runs moved left and reached J = −0.06 to −0.10, roughly doubling WF's
     distance from the empty state.
   - WF → right: all 3 runs also moved right. Run 0 ended at +0.0447, beyond the empty state
     and beyond CM's starting point.
   - CM → left: all 3 runs moved left, but mostly by small amounts.
   - CM → right: only 1 of 3 runs moved right (+0.059); the other two ended left of the start.
3. **Each drawn answer swings J more than the expected push.** The chosen questions have
   |μ| ≈ 0.004–0.015, but single answers move J by up to ±0.04. Examples:
   - WF `homosex` = "always wrong" (p = 0.34): +0.041.
   - CM `ABHELP3` = "yes" (p = 0.40): −0.023.

   With 3 runs per case the greedy means are rough. Each run's end varies by about ±0.03.
4. **Most of CM's push to the left comes from one-sided questions.** 10 of its 18 steps used
   items where every answer lowers J: mother's occupation code `MAOCC10`, museum visits
   `vissci`/`visnhist`, and `wrkstat`. Filling in any answer to these moves the state toward
   the left pole, whatever the content. This is a property of the metric, not an opinion
   signal. Content questions such as `abmoral` sometimes push CM the other way.
5. **The questions chosen have recognisable themes.** Right pushes use gun ownership
   (`pistol`, `rifle`), religion (`god`, `hell`, `heaven`, `godmeans`), abortion-funding items
   (`ABHELP2/3`), the 2012/2016 vote, and `homosex`. Left pushes use abortion attitudes
   (`abmoral`, `ABSTATE2`, `abinspay`, `abhlth`), religion (`sprel`, `miracles`), and the
   one-sided demographic and museum items.
6. **Earlier answers change what is asked next.**
   - CM: after `PRES12` = romney, `PRES16` becomes the next choice. After obama, it is not chosen.
   - CM: `ABHELP2`'s μ rose from +0.0015 at the start to +0.0149 after `ABHELP3` = no.
   - WF: `ABSTATE2` and `abinspay` appear only after `abmoral` = "it depends".

   So one-step μ values do not simply add up over a run.
7. **Non-substantive answer codes count as answers.** Examples: `PRES16` = "iap" (inapplicable,
   p = 0.28) and `pistol` = "refused". A step that draws one of these moves J by about zero.

## Caveats

- These are information-conditioning effects of a fixed model, not opinion change in people.
- The native P(a|s,v) is close to the population marginal for most items (see
  `ONE_STEP_FINDINGS.md`). The answer draws are therefore close to population draws, not
  persona-specific ones.
- 3 greedy runs per case is too few to estimate the greedy means precisely.
- The random baseline uses the same 120-question pool. That pool is enriched for one-sided
  left-moving items, so the baseline is not neutral.
- The persona states are the committed reference states, not the LLM-decoded library states.

## Possible next steps

- Run 20+ greedy runs per case. The incremental-distance speedup would make this practical.
- Draw the random baseline from all non-pole questions.
- Add an option to exclude iap / refused / don't-know answers.
- Add a `content_only` policy that skips one-sided questions, and a variance-aware policy
  that maximizes P_up or μ − λ·sd.

## Files

- `greedy_runs/{CM,WF}_{right,left}_n6.csv`: every step of every run (question, μ, P_up/P_down,
  drawn answer and its p, ΔJ, J after).
- `greedy_runs/*.json`: state, seed, J₀ and the audit.
- `greedy_runs/summary.md`: step-by-step tables for every greedy run (from `greedy_runs_summary.py`).
- Code: `greedy_push_runs.py`, `greedy_runs_summary.py`, and `optimizer/one_step_geometry.py` (`policy_run`).
