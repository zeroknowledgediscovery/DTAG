# Validated DTAG synthetic trajectory question sets

These files collect the best currently validated 5-10-question synthetic DTAG trajectory sets recovered from the GSS-2024 optimization work.

## Scope

These are simulation/model-sensitivity assets for synthetic CM/WF DTAG initializations. They are not intended for targeting, persuasion, campaigning, or behavioral manipulation of real people or populations.

## Sets

### `gss2024_cm_up_wf_down_10.csv`

Ten-question synthetic trajectory set validated with stochastic state updates and independent CM/WF response streams.

Untouched 400-run validation block:

- CM change: approximately +0.0117, 95% CI [+0.0029, +0.0214]
- WF change: approximately -0.0164, 95% CI [-0.0266, -0.0060]
- separation change: approximately +0.0281, 95% CI [+0.0135, +0.0421]

Source result:
`assets/question_sets/polarization/gss2024_polarize_cm_wf_draw_10.csv`

### `gss2024_cm_down_wf_up_10.csv`

Ten-question prefix of the validated depolarization sequence.

Untouched 400-run validation block:

- CM change: approximately -0.0207, 95% CI [-0.0317, -0.0087]
- WF change: approximately +0.0227, 95% CI [+0.0118, +0.0339]
- separation change: approximately -0.0433, 95% CI [-0.0593, -0.0270]

Source result:
`assets/question_sets/depolarization/gss2024_depolarize_cm_wf_draw_12.csv`

## Optimization code

Current generalized code:

`applications/question_sequence_optimization/`

Historical stochastic optimization code:

`scripts/optimize_question_sets.py`

Full historical analysis:

`QUESTION_OPTIMIZATION.md`

The same-direction both-up and both-down candidates are not copied here yet because the existing versions are modal-response candidates and have not received equivalent held-out stochastic validation.
