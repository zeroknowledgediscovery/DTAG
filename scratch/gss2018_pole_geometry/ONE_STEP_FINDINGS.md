# GSS 2018: exact one-step survey-item response geometry (findings)

Handoff task §11, run on branch `dev-claude`. Native GSS 2018 LSM (release v0.2.1),
original 38-item 2018 poles (`assets/polar_vectors/gss/gss_2018_polar_vectors.csv`,
unchanged, none dropped), J(s) = I(s) − I(∅). Exhaustive: every unassigned model
variable × every valid native label. No LLM, pruning or sampling.

Full auto-generated tables: `ONE_STEP_REPORT.md`. Data: `one_step_results/{CM,WF}/`
(`response_level.csv` = one row per (variable, answer); `variable_summary.csv` = one row
per variable; `metadata.json` = state, checksums, timings, validation).

## Which persona states were used (differs from the handoff table)

The LLM-decoded library states behind the handoff's CM +0.00619 / WF −0.04219
(`outputs/optimizer/sequence_library_empty_centered_v1/cache/gss_2018_base_personas.json`)
are local, uncommitted outputs and were not available here. The run therefore uses the
committed rich reference states (`assets/question_sets/personas/target_states.json`,
filtered by the 2018 model), the same states as `CENTERED_FINDINGS.md`:

| Persona | assignments kept | I | J |
|---|---:|---:|---:|
| CM | 8 of 15 | +0.08637 | +0.02633 |
| WF | 7 of 15 | +0.02426 | −0.03578 |

The 2018 model rejects age, region, childs, xnorcsiz, news, wrkstat and vetyears (and
WF's degree) because their labels are spelled differently in the 2018 model. To rerun on the decoded
states: `--personas-json <that cache file>`.

## Validation (all passed, both personas)

- 7,149 (CM) / 7,154 (WF) pairs; every answer is a valid native label.
- I(∅) = 0.06004654, matching the handoff.
- max |ΔI − ΔJ| ≤ 1.4e−17 (centering never changes displacement).
- 300 random pairs re-evaluated: bit-identical (deterministic).
- Raw native P(·|s,v) sums to 1 (±1e−16); zero off-support mass; no all-zero items.
- Σ_a P·I(s_{v,a}) − I(s) reproduces μ_v to 1e−17.
- Serial vs 4-worker parallel (CM): identical I and P on all 7,149 rows.
- Cost: ~32 ms per index evaluation unloaded (~88 ms per pair with 3 jobs sharing 4 CPUs).
  An exhaustive one-step sweep takes ~4 min per persona serially, so no acceleration is
  needed at depth 1. Depth 2 would need ~7k² ≈ 5×10⁷ evaluations, which does need it.
- `World.I` silently returns 0.0 on nonfinite distances. This script computes distances
  directly and fails instead. `World.dists` silently drops off-support labels and
  renormalizes, so the script audits the raw distribution first.

## Results

1. **Sensitivity is concentrated in few items.** The median non-pole range R_v is ≈0.0025.
   About 130 of ~990 non-pole items have R_v > 0.01, and ~190 have R_v exactly 0: no
   answer moves I at all. Pole items have a median range of 0.039, ~15× larger, as expected
   since they write directly into pole coordinates. Pole and non-pole items are reported separately.
2. **Most sensitive non-pole items are the same for both personas**: abortion items
   (ABHELP1–4, abinspay, abmoral), homosexuality (homosex, spkhomo), religion (god,
   heaven, reborn, savesoul, godmeans), premarsx, guns (rifle, pistol), and PRES12/PRES16.
   The maximum non-pole range is 0.066 (ABHELP2), larger than the CM−WF gap in J (0.062).
   Spearman(R_CM, R_WF) = 0.98.
3. **Extremes are mostly not improbable.** Among the top 1% of |Δ| rows, the median
   P(a|s,v) is ≈0.23 and only 15–19% have P < 0.05. So the envelope is not driven by
   implausible answers.
4. **Expected one-step drift is leftward for both personas.** Σ μ_v over non-pole items
   is −0.21 (CM) and −0.18 (WF). μ_v < 0 for 65% (CM) / 52% (WF) of items, and > 0 for
   26% / 38%. Median μ is ~1e−5, so this is a sum of many tiny shifts. It agrees
   qualitatively with the library runs' frequent "negative translation". 137 items are
   expected to converge (μ_CM < 0 < μ_WF) and 21 to diverge.
5. **Key caveat: the native conditional distributions barely depend on the persona.**
   For the median variable, P(a|CM), P(a|WF) and P(a|∅) are identical: TV distance 0.
   87% of variables are within TV 0.01 of the empty-state marginal; 90th percentile
   TV(CM, WF) is 0.026 (`one_step_results/conditioning_strength.csv`). For example,
   P(ABHELP2), P(spkhomo) and P(god) are the same for a weekly-churchgoing strong
   Republican and a non-religious extremely liberal Democrat. Conditioning acts mainly on
   items close to the assigned demographics (sexbirth, reliten, fund, PRES16, …). With
   these sparse states, μ_v and σ_v are therefore close to *marginal* expectations, and
   the CM/WF similarity in findings 2–4 is partly a consequence. Questions to resolve
   before building multi-step expected trajectories:
   - Is this native-runtime behaviour (missing parents marginalized to population priors)
     intended?
   - Do the richer LLM-decoded states condition more strongly?

## Which question to ask (argmax / argmin of mu)

You choose the question; the model draws the answer. So the ranking criterion is
mu_v = E[Delta]. delta_plus/delta_minus are best cases that occur only with probability
p_answer_plus / p_answer_minus. Full top-25 lists: `one_step_results/{CM,WF}/mu_rankings.csv`.
Definitions and top-10 tables: `ONE_STEP_REPORT.md`.

| Persona | push right (argmax mu), non-pole | push left (argmin mu), non-pole | pole item, strongest |
|---|---|---|---|
| CM | PRES12 +0.0088 (P_up 0.80), pistol +0.0085, ABHELP3 +0.0080 | MAOCC10 −0.0077, MASEI10EDUC −0.0072, vissci −0.0065 (all one-sided), abmoral −0.0059 | reliten +0.038 (P_up 0.94) |
| WF | pistol +0.0085, god +0.0073, hell +0.0068 (P_up 0.85) | MAOCC10 −0.0077, sprel −0.0074, MASEI10EDUC −0.0072, abmoral −0.0062 | reliten −0.040 (P_down 0.79) |

- Best expected one-step moves are ≤ 0.009 for non-pole items, ~15% of the CM−WF gap (0.062).
- Several top push-left items are `one_sided` (every answer moves left, P_down = 1): filling
  that coordinate moves s toward L regardless of content. This is a property of the metric,
  not an opinion signal. Filter `one_sided` if only content-driven moves are wanted.
- reliten is the only strong question that pushes CM and WF apart. It is a pole item.
- Reusable function: `optimizer/one_step_geometry.py` (any model, poles and known-answer set),
  checked bit-for-bit against this reference.

## Not done / next

- Rerun on the LLM-decoded library states (spec 00–04) once that cache is provided.
- Depth-2 enumeration on the ~130 high-range items, to measure non-additivity
  Δ_{v,w}(a,b) − Δ_v(a) − Δ_w(b) directly.
- Interpretation: these are information-conditioning effects of a fixed model, not opinion change.
