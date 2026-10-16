# Deferred research notes: DTAG ideology-index sequence experiments

**Status:** Deferred — revisit only after the basic CM/WF optimizer, mapping, and
held-out validation workflow runs reproducibly end to end.

**Scope:** Research on how conditioning a fixed GSS 2024 Large Science Model (LSM)
on additional survey answers changes its inferred ideology index. These are
**model-state changes**, not evidence that a survey changes people's political
beliefs. This document preserves questions and potential diagnostic experiments;
it does not change the current code or search configuration.

## Current baseline to preserve

- Native GSS 2024 LSM; wave-specific ideology poles.
- Persona sources: `assets/question_sets/personas/gss2024_{cm,wf}_rich.txt`.
  The actual LLM-decoded assignments are protected throughout each simulated run,
  including `polviews` and `partyid`.
- Historical config: `configs/optimizer_gss2024_cm_wf_baseline.yaml`.
- Expanded-search config: `configs/optimizer_gss2024_cm_wf_robust.yaml`.
- Original run discussed in chat: nine-question prefix selected from a ten-question
  search; 50 starting-state attempts per CM/WF persona, 20 answer draws per state
  (2,000 trajectories before duplicate-state clustering). Reported outward-signed
  mean changes: **CM/positive +0.0023** [0.0021, 0.0026];
  **WF/negative +0.0030** [0.0028, 0.0032].
  Separation change approximately **+0.00535** [0.00503, 0.00566].
  The run reported **98%/100%** of starting states having positive mean outward
  change; these are NOT per-trajectory outward probabilities. Random-set
  objective percentile was 100% among only 20 sampled controls.
- Earlier, methodologically different historical ten-question validation reported
  separation change about **+0.028** [0.013, 0.042]. Do **not** interpret the
  difference as a measured loss in performance without matched re-evaluation.

## A. Four directional response regimes (analyze after baseline is stable)

For each actual *initialized* state, let
`I0 = I(start)`, `I1 = I(after sequence)`, and `delta = I1 - I0`.
Use the actual starting sign, not an assumed persona label.

| Regime | Initially positive group: raw delta | Initially negative group: raw delta | Geometric interpretation |
|---|---:|---:|---|
| Divergence | > 0 | < 0 | Both outward |
| Positive translation | > 0 | > 0 | Both indices increase |
| Negative translation | < 0 | < 0 | Both indices decrease |
| Convergence | < 0 | > 0 | Both inward *if there is no overshoot across zero* |

For future **descriptive evaluation**, classify outcomes from a common,
pre-specified set of neutral survey sequences using the two *raw* group means.
Do not classify all regimes using `sign(I0) * delta`; that statistic is useful
for outward movement only and loses the direction of translation.

Further questions:
- Does each regime exist in the fixed-model conditional response geometry?
- How common and how stable is each regime across independently sampled
  starting states, answer seeds, and repeated validation blocks?
- Does an apparent inward shift cross zero (overshoot) rather than approach it?
- How do magnitude and state-level reliability compare with random and
  shuffled-order controls?

## B. Why is the observed magnitude small?

Treat these as hypotheses to test, not established explanations.

1. **Current objective rewards consistency more than effect size.**
   `optimizer/search.py` scores the smaller of the two group t-statistics,
   which can favor a tiny effect with very low sample variance over a larger
   but noisier effect. The initial greedy log included `+inf` and t-like
   scores on the order of `1e13`, indicating zero or near-zero variance
   in very small search batches. Increasing repetitions alone is not a
   mathematical fix. Later: quantify the frequency of nonfinite/unstable
   objectives, consider finite regularization, and report effect magnitude
   separately from confidence or consistency.

2. **Newer selected items may affect pole distances only indirectly.**
   The logged question IDs (`getahead`, `relactiv`, `classtech`,
   `suicide2`, `wlthhsps`, `usmca2`, `urbantech`, `forland`,
   `confinan`, `conscrp`, and local-search replacements) do not
   directly coincide with the 27-variable GSS 2024 ideology-pole file.
   Earlier validated sequences contained several pole variables
   (`pray`, `abpoor`, `bible`, `natarms`, `natsoc`, `polabuse`).
   Later: compare direct pole-item updates with non-pole updates on
   **matched** starting states. Explicitly distinguish geometric effects
   from bank restrictions and mapping behavior.

3. **All mapped persona facts are now immutable.**
   The current `protect_mapped: true` design safeguards identity and
   makes initial conditioning reproducible, but may narrow accessible
   changes. The older historical experiments allowed broader perturbation
   in several demographic or ideological attributes. Later: audit which
   variables were fixed, dropped, resampled, or inferred across the
   protocols; compare alternatives while preserving explicitly required
   political anchors. Do not weaken the anchor-invariance assertions
   accidentally.

4. **The index has a meaningful geometry and scale.**
   `I(s) = [d(s_L,s) - d(s_R,s)] / d(s_L,s_R)`. A shift of 0.005 is
   not interpretable without initial CM/WF separation, empty-state
   reference, observed random-question changes, and within-state response
   variability. Later: report raw changes, relative change versus the
   initial gap, trajectory-level distributions, and distance-to-pole
   contributions `d_L` and `d_R`.

## C. Technical and statistical follow-ups

- **Search-score degeneracy:** investigate zero/near-zero group standard
  errors in `optimizer/search.py`. Avoid treating `+inf` as the best
  possible outcome. Keep search selection and held-out assessment separate.
- **Actual initialized ideology:** continue grouping each run by the
  sign of its *post-perturbation* `I0`; log sign flips and neutral-band
  crossings (`neutral_band: 0.005`).
- **Independent units:** repeated response draws from one initialized
  state are nested. Bootstrap distinct states for local robustness,
  ideally accounting for the fact that states arise around two fixed
  persona templates. Don't call 2,000 draws 2,000 independent respondents.
- **Range of initial states:** assess movement against `I0` and stratify
  by `|I0|`; add additional independently specified persona templates
  or held-out real survey records for wider generalization claims.
- **Baselines:** compare question content, ordering, matched random-bank
  sequences, and the historical 10-item sequence under identical
  mapped variables, starting states, seeds, and response mode.
- **Mapping and anchors:** audit `bank.mapping: verify` for extra
  unintended variables; source recall is not exact set agreement.
  Save full variable mappings and enforce protected-assignment invariance.
- **Reproducibility:** retain exact config, model/map/poles hashes,
  LLM-decoded initial states, question bank, random seeds, and outputs
  under distinct directories. Never overwrite the previous baseline.
- **Uncertainty and interpretation:** report both group means with
  state-level intervals, state-level share outward, trajectory-level
  share outward, effect sizes, and changes to `d_L` and `d_R`.
  Statistical significance does not imply a large effect or real-world
  belief change.

## Suggested order once basic functionality is settled

1. Freeze an end-to-end reproducible run and save its exact configuration
   and mappings.
2. Diagnose numerical degeneracies, trajectory variance, and whether
   pole overlap explains the magnitude difference.
3. Re-evaluate old and new question sequences using matched starting
   states and a common bank/mapping protocol.
4. Add *descriptive* four-regime diagnostics for pre-specified neutral
   question sequences, including raw group changes and overshoot checks.
5. Expand initial-state coverage and repeat independent hold-out audits.

**Not for the current baseline milestone:** no immediate changes to
`optimizer/search.py`, `my.yaml`, or the versioned YAML files are implied
by this research note.
