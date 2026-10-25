# Completed 36-question internal pilot: respondent-facing wording review

Date: 2026-10-24 (America/New_York). Source: investigator's
`human_study/scripts/audit_completed_questions.py --show-original` output for a
completed archived `pilot-001` session. This report deliberately omits the
session ID, participant answers, treatment assignment, and ideology scores.

**Disposition: technical end-to-end success; instrument NOT approved for
Prolific recruitment or validity claims.** The previous heuristic audit
reported 36 shown, 27 flagged, 13 FAIL and 26 REVIEW. Those are overlapping,
automated screening flags, not a scientifically adjudicated failure count.

## Material issues in questions actually displayed

| Ordinal(s) | Variable(s) | Assessment | Required action |
|---|---|---|---|
| 01 | `confinan` | **Invalid target**: LLM wording says only "this institution" and never names **banks and financial institutions**. Reverse mapper reported `mapper_hit=True`, demonstrating that mapping is not a wording-fidelity guarantee. | Pin complete respondent-facing wording that names the target; add target-entity assertion and official source reference. |
| 02–10 | `conbus`, `coneduc`, `conpress`, `conmedic`, `contv`, `conjudge`, `consci`, `conlegis`, `conarmy` | **Non-standalone source formatting**: app displays shared GSS introductory stem in parentheses, followed by the institution after the question mark. Flagged as `canonical-common-instrument`, although it is not a standalone question. | Curate individual, consistent confidence questions naming each institution; do not show map metadata verbatim. Preserve unmodified source and native answer codes. |
| 17 | `eqwlth` | **Uninterpretable scale**: options include `2.0`–`6.0` without numeric scale definition/endpoint labels. Binary-sounding generated question does not explain the graded scale. | Verify the complete 2024 seven-point stem/anchors and the native-category-to-display mapping; provide anchored scale labels or exclude. |
| 23 | `helpnot` | **Uninterpretable scale**: options include `2.0` and `4.0` alongside semantic endpoints and "agree with both". | Verify actual 2024 questionnaire form and full response categories, then provide validated labels or exclude. |
| 32 | `workhard` | **Invalid isolated ranking**: "How important is working hard to you?" is not answerable using positions `most important`, `2nd important`, etc. The task requires a specified comparison list. | Exclude unless complete forced-ranking task and compatible coding/selection are implemented. |
| 20 | `getahead` | **Automated false positive**: "most important" refers to hard work versus luck, not a five-position child-values ranking. The displayed three choices are interpretable. | Remove the overbroad ranking regex trigger; still verify wording against the 2024 questionnaire. |
| 25 | `fefam` | **Substantive rephrasing needs review**: displayed "man works outside the home" versus source "man is the achiever outside the home". These are not automatically equivalent. | Restore/check complete original wording and keep semantics stable. |
| 33 | `natenviy` | **Form-specific verified correction passed**: display asks about spending on "the environment"; provenance `verified_2024_form_specific_reference_v1`, `mapper_hit=False` by design. | Retain explicit 2024 alternate-form provenance; do not silently substitute `NATENVIR`. |

## Items without obvious screening failures, but not source-verified here

- Baseline `trust`, `fair`, `helpful` (11–13): understandable and aligned with displayed choices.
- Adaptive `natheal`, `letin1a`, `fejobaff`, `natcity`, `nateduc`,
  `natrace`, `natcrime`, `natcrimy`, `natsci`, `nataid`,
  `natenrgy`, `natspac` (14, 15, 16, 18, 19, 22, 24, 26–29, 31):
  generally intelligible spending/attitude questions, but rely on incomplete
  excerpts and reverse mapping, **not verified full 2024 stems**.
  `fejobaff` wording also merits careful response-scale review.
- Adaptive `health` and `happy` (21, 30): self-contained, understandable.
- Outcomes `cappun`, `courts`, `tax` (34–36): self-contained,
  understandable; still independently verify their specific 2024 forms.

## Scientific implications

1. **Successful LLM reverse mapping is insufficient for instrument validity.**
   `confinan` mapped to the intended variable despite omitting its subject;
   `workhard` mapped despite changing the measurement task.
2. **Verbatim fallback is not the only failure mode.** Complete, plausible
   reformulations can lack defining construct/scale context. Markers for
   `source_text_incomplete` also miss the nine baseline institution labels.
3. **Answer labels are part of the measurement contract.** Numeric intermediates
   must be shown with meaningful position/anchor labels. Original native values
   should remain unchanged behind the UI.
4. **Experimental comparability matters.** Differences in wording or response
   scales between respondent groups can confound claimed DTAG-induced movement.
   This technical pilot's outcomes should not be treated as validated evidence of
   ideology change or construct refinement.

## Proposed instrument v2, before any further human recruitment

1. Add explicit `participant_wording` (or an audited stem+topic renderer)
   separate from `original_wording`; require source/form citation, item version
   and native display-label mapping for every reviewed item.
2. Pin canonical, independently reviewed questions for baseline and outcome
   phases. For nine institution items, combine their shared GSS confidence stem
   with the correct named institution into a standalone prompt; explicitly name
   *banks and financial institutions* in `confinan`.
3. Verify 2024 seven-point scale anchors for `eqwlth`, `helppoor`,
   `helpsick` and `helpnot`, since they share unexplained numeric-code
   problems. **Do not fabricate anchor mappings**; until validated exclude
   those items from the intervention bank.
4. Exclude `workhard`/`helpoth` until the full relative-ranking experiment
   can be administered and mapped to legitimate individual response values.
5. Freeze audited items and reject deployment if any included question is
   non-standalone, has unlabelled numeric choices, is a ranking task without a
   comparison set, or lacks approved scale semantics. LLM generation can be an
   *experimental* transformation under explicit provenance, not a silent repair
   for unavailable item metadata.
6. Recalculate eligible adaptive-pool size *after* excluding invalid items.
   The current 28-item intervention bank may become too small for 20 steps
   depending on geometry/pole exclusions. Add independently verified items
   or explicitly revise intervention length and study version; do not weaken
   eligibility checks.
7. Save an instrument-versioned, investigator-reviewed staging YAML externally;
   preserve all old immutable GCS objects and completed-session provenance.
   Run a new full 36-item dry test, archive audit and scientific trajectory
   inspection before starting Prolific recruitment.

## Sources for additional verification

- Official NORC 2024 cross-section questionnaires:
  https://gss.norc.org/get-documentation/questionnaires.html
- GSS 1972–2024 cumulative codebook (`confinan` example):
  https://csmweb-prod-02.ist.berkeley.edu/sdaweb/docs/gss24rel1/DOC/hcbk0079.htm
- This repository's `human_study/WORDING_SOURCE_AUDIT.md` documents
  incomplete map text and the verified `NATENVIY` form-specific correction.

**Scope:** This review is based on actual displayed text and recorded choices
from the investigator-provided archive audit. It is not a line-by-line review
against all three official 2024 source questionnaires or a validation of the
native model's numerical predictions.
