# DTAG multi-persona push study (manuscript experiment)

Status: **script and analysis plan implemented, results not yet validated**. Scientific
endpoint: conditional `I_t-I_0` trajectories under adaptive question selection. These
are synthetic updates of an unchanged native GSS model, **not human persuasion**.

## Design

Use the six **pinned** personas already defined in
`optimizer/personas/gss2024_spectrum.yaml`, arranged in three conservative /
liberal pairs:

| Pair | Conservative | Liberal |
|---|---|---|
| 1 | `cm_rural_alabama` | `wf_new_york_city` |
| 2 | `religious_conservative_woman_texas` | `secular_liberal_man_seattle` |
| 3 | `hispanic_catholic_man_arizona` | `black_churchgoing_woman_atlanta` |

Descriptions and response assignments are examples of **synthetic** individuals; no
population representativeness or causal inference is implied. The paper should state
both the GSS `polviews` label and the **actual initial pole-relative geometric
index**; their signs need not correspond perfectly. The script prints and records
the actual index, retaining the same six personas across all policies.

Every persona gets four policies:

1. **Push R (up)**: adaptively maximize the native expected one-step index
   displacement `mu_v(s)`, ask selected item and sample an answer.
2. **Push L (down)**: adaptively minimize `mu_v(s)`, then sample.
3. **Neutral geometric control**: select the item minimizing `|mu_v(s)|`, then
   sample. This is neutral only in **expected index drift**, and it may have high
   realized variance; it is not a psychologically neutral question.
4. **Random-question control**: uniformly sample an eligible, unasked opinion
   item, then draw its answer from the exact native conditional response model.

The candidate pool is the **same across arms** at baseline: the
`optimize_question_sets.askable` opinion-item filter used by the DTAG web app
push suggestions. Pole-defining, administrative, demographic, factual-behavior,
and already known items are unavailable as questions. Initial persona assignments
are pinned. At every step, candidate items are re-evaluated at the **new**
synthetic state; question choice is never based on future sampled answers.

This study uses the native `optimizer.one_step_geometry.policy_run` CLI code
path, with `neutral_mu` added to that function. All policies use response
mode **draw**. `I(s)` is the unchanged registered GSS geometry. This is the
idealized **direct item** version of DTAG: no LLM semantic mapping, no natural
language rendering. A separate realistic/validated LLM-mapping study is needed
before claims about conversational questions.

### Uncertainty

- Each of `--reps` runs fixes the same persona anchors but uses an independent,
  deterministic response draw stream for each policy.
- Pointwise 95% bootstrap intervals summarize the **mean trajectory** over
  stochastic synthetic draws. Replications are Monte Carlo draws, **not**
  independent human participants.
- The manuscript should show six subplots arranged as three paired rows
  (conservative and liberal columns), with four mean `I_t-I_0` curves and their
  uncertainty ribbons per panel.
- Table: `endpoints.csv` provides 95% CIs of terminal changes; `versus_random.csv`
  provides bootstrap CIs for run-index-matched differences against random.
- The secondary figure compares terminal effects across personas. All plots are
  **generated from actual CSV results**, not mock estimates.
- Intervals are pointwise (not simultaneous across steps), conditional on each
  **fixed** initial state, model fit, pole vectors and the specified policy.
  They exclude model-fit uncertainty, sampled-persona uncertainty, mapping
  uncertainty, and human-participant variability.

## Execute on a machine with native DTAG support

From repository root, branch `dev`:

```bash
git checkout dev && git pull --ff-only origin dev
python -m pip install -r requirements.txt
bash scripts/build_native_bindings.sh        # if incremental native backend is absent

# plumbing check only -- two draws do NOT yield useful scientific CIs
python scripts/dtag_persona_push_study.py \
  --quick --workers 4 --out outputs/dtag_persona_push/smoke

# main experimental run (recommended paper configuration)
python scripts/dtag_persona_push_study.py \
  --model gss/gss_2024 \
  --reps 40 --steps 10 --bootstrap 2000 \
  --seed 20261021 --workers 4 \
  --out outputs/dtag_persona_push/main
```

To reduce cost initially, use `--reps 10 --steps 6`. For a stronger figure,
increase `--reps 100` after confirming a full trial's runtime. The main
configuration executes `6 personas x 4 policies x 40 repetitions = 960`
sampled trajectories, each of up to 10 questions. Expect the exact greedy and
neutral passes to dominate runtime. Repetitions can be parallelized across
`--workers` processes, with one native LSM world initialized per worker.
Ensure model downloads and memory availability first.

## Outputs

- `manifest.json`: seeds, complete pinned states, model/map/poles provenance,
  exact candidate eligibility, mode and setup.
- `trajectories.csv`: every question, variable, native answer, its conditional
  probability, predicted drift, realized `I` and `I-I0`.
- `trajectory_ci.csv`: pointwise mean and 95% bootstrap CI at every step.
- `endpoints.csv`: net changes, CIs and movement fraction per persona/arm.
- `versus_random.csv`: differences from matched stochastic random baselines.
- `question_counts.csv`: frequently selected questions, for interpretation.
- `persona_push_trajectories.pdf/png`: paired six-panel trajectory figure.
- `persona_push_endpoints.pdf`: terminal-change comparison with 95% intervals.

Files are written under `outputs/` (ignored by Git). To create a permanent
science record, attach a run manifest and the resulting CSV/figure artifacts
only after execution and inspection.

## Publication-relevant tests

1. Is expected rightward/downward movement monotonic in the average under
   adaptive policy, and how often does realized movement reverse?
2. Is an outward shift consistently present for both liberal and conservative
   personas? Report signed direction relative to **actual I0** and changes
   in separation across the three persona pairs; do not infer it from self-reports.
3. Do both push policies differ from random item selection with uncertainty
   intervals excluding zero for `I_T-I_0` comparisons? Which personas are
   responsive to both directions?
4. Does `neutral_mu` actually suppress expected displacement, and what is
   the realized variance?
5. Which opinion questions dominate each policy; are results robust to
   excluding pole-related content, switching GSS wave, and changing the
   initial state? These are analysis checks, not yet performed here.

Do not interpret movement of the model's geometric index as measured changes
in a human respondent. The subsequent Prolific experiment tests that distinct
hypothesis, with randomized exposure and independently measured outcomes.
