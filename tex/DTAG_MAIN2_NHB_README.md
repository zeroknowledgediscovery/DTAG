# DTAG manuscript 2: Nature Human Behaviour framing

## Files and status
- `tex/dtag_main2.tex`: independently written Nature Human Behaviour-oriented ARTICLE draft.
- `tex/references_nhb.bib`: incremental survey-method and opinion-structure citations.
- Existing `tex/references.bib` and pre-rendered figure PDFs are reused.
- **Nothing in `dtag_main_new.tex`, `humanstudy_new.tex`, or existing TikZ externalization commands has been changed as part of this draft.**
- The manuscript is a scientific draft, not the Nature publisher's LaTeX typesetting template. The full PDF has not been compiled or visually checked in this environment.

## Distinct thesis
**Question selection is part of the measurement instrument.** The measured pole-relative ideology index is a function of both a respondent's observed answers and which answers the selection policy elicits. In 71 actual respondent sessions, directional selection reveals asymmetry and an early operational resistance phenotype; this is not evidence of changed political beliefs.

The original paper is an LSM/DTAG technical methods article. This paper is a behavioral-measurement article and places the human findings before implementation detail.

## Existing evidence that can be stated
1. Simulated: 960 trajectories (6 personas x 4 policies x 40 replicates), 20 questions each, direct LSM sampling, all 27 index-pole questions excluded.
2. Replays: 2,880 20-question fixed-set LSM replays, original/reversed/shuffled orders, no detected systematic mean order effect at the tested resolution.
3. Calibrated human: 71 completed sessions; Left 21, Right 38, Neutral 7, Random 5. Left directional success 20/21; Right 21/38. Mean endpoints -0.0989 (95% bootstrap [-0.1200,-0.0741]), +0.0225 ([+0.0006,+0.0452]).
4. Right heterogeneity: initially-Left 12/29 rightward; initially-Right 9/9. The Left arm: initially-Left 16/17 leftward and initially-Right 4/4.
5. Q4 early nonmovement for initially-Left Right-push: TP=17, FP=2, FN=0, TN=10 on final nonresponse; this rule and outcome were evaluated in the same 29 people.
6. Exploratory question analysis: colath, religion/sexual attitudes and civil liberties are salient selections. Spending exposures 13.75% versus 7.35% in initially-Right/Left Left-push (two-sided permutation p=.0894), but normalized positive movement share 8.06% versus 7.36% (p=.8932). The Ellis–Stimson *operational liberalism* account is a testable background explanation, not an established mechanism.

## Figure plan
- Main Fig 1: existing native architecture+simulation external PDF dtag-fig1.
- Main Fig 2: existing 71-person four-panel human external PDF dtag-fig3.
- Extended Data Fig 1: existing question selection and fixed-set order analysis PDF dtag-fig2.
- Extended Data Fig 2: existing Q4-filtered Right response PDF dtag-fig4. This is a **selected subgroup illustration**, not independent proof of efficacy.
- Figure inputs are referenced but existing figure code, caches and externalization directives are untouched.

## Key additional analyses (do not invent outputs)
A. **Prediction-versus-realized displacement** from archived per-question expected target-only and full observed update fields, stratified by policy, baseline phenotype, study wave and assignment count. This is the highest-value bridge between native simulations and human behavior; predicted target-only changes and observed multi-variable updates are not identical estimands.
B. **Model-independent measurement check**, e.g. preregistered held-out GSS item battery, independent self-reported ideology, or paired fixed-answer counterfactual replays. Without this, the outcome is optimized against the same model that scores it.
C. **Wave-aware comparisons**, including original four-policy randomized subsample, and uncertainty intervals for baseline subgroup rates. Cross-wave pooled arm counts cannot establish causal effectiveness.
D. **Early-rule validation**, comparing Q4 against Q1/Q2 and later-window displacement Q4-to-Q20, and independent recruited cohort. The current TP 17/17 should not be described as universal sensitivity.
E. **Question contribution validation**: mapping native answer category to step increments, model-predicted versus actual and multi-variable assignment sensitivity; audit reference pole specification including potentially counterintuitive polabuse coding.

## Submission metadata (must be verified)
- University ethics approval/exemption number, consent text and procedures.
- Exact participant inclusion, Prolific study/recruitment waves, eligibility and compensation.
- Demographics, preregistration history, deviations from protocol, pilot vs main samples.
- Frozen source/model/software version, LLM version and mapping-validation performance.
- Reproducible data/code availability, deidentified analyses and privacy safeguards.
- Author contributions, potential startup/IP interests, funding.
- Double-anonymized review preference and author list.

## Build
From DTAG repository root, after fetching the new branch and ensuring existing external figure PDFs exist:

```bash
cd tex
latexmk -pdf -interaction=nonstopmode -halt-on-error dtag_main2.tex
```

The source uses `natbib`, `unsrtnat` and `references,references_nhb`. If the cached `dtag-fig4.pdf` is not present, it can be generated from the private analysis export and PGFPlots sources used in the original technical draft. Figure guards leave a visible placeholder instead of substituting false data.

## Editorial fit
Nature Human Behaviour's scope includes political behaviour, belief systems, and measurement of individual differences. Its preparing-submission criteria consider conceptual advance, rigor, sample size, analysis transparency and public significance. Editorial guidance warns against titles/abstracts that overstate external validity. The journal does not accept presubmission enquiries for original research articles. Consult its current guidance when preparing final materials.

## New explanatory table (31 October)
- `tex/Figures/dtag_nhb_top_item_summary.csv` contains **14 aggregate
  rows**: the top seven positive-leftward target questions for each
  baseline subgroup of participants assigned Left push (initially Right,
  n=4; initially Left, n=17). These values were transcribed from the
  investigator-supplied output of the archived private item analysis,
  not recomputed from private individual records in this commit.
- `tex/Figures/dtag_nhb_top_item_table.tex` is the corresponding manuscript
  Table 1, included by `dtag_main2.tex`. It reports selection counts,
  total positive leftward displacement, mean positive displacement per
  selection, and net leftward displacement, with human-readable question
  topics from the GSS 2024 map. Counts are selections, not the number
  of unique respondents. Positive movement and net movement can disagree.
- To update/freeze this table, rerun the existing private exporter
  `human_study/scripts/analyze_item_directional_contributions.py` and
  recompute the public aggregate table from
  `target_questions_PRIVATE.csv`; audit row values and topic labels
  before regenerating TeX. **Do not commit the private exporter output.**
- This table addresses `which selected questions accompany Left-directed
  index changes`. It **does not** explain Right-push resistance, which
  requires an independent comparison of the early-flagged and unflagged
  Right-push subgroups.

### Most valuable additional explanatory analysis
1. For the 29 initially-Left Right-push participants, split by the Q4
   rule (19 flagged, 10 unflagged), and compare selected question targets,
   net directional increment per question, and multi-variable mapping
   frequencies separately for Q1--Q4 and Q5--Q20. Stratify by study wave.
2. Compare each selected question's LSM-predicted `predicted_target_only_delta`
   with its actual `observed_step_delta`, noting that the latter can
   contain several jointly accepted survey-variable assignments. Look for
   systematic prediction error in the Q4-flagged subgroup.
3. Examine the accepted native **response values**, not just selected
   variable names, for high-gain items. Without values, the mechanism
   cannot distinguish selector choice from the direction of a participant's
   actual answer. Avoid inferring that a participant changed their belief.
4. Measure sensitivity of movement to reference-pole choices and assess
   held-out or independently measured ideology where feasible. This is
   important for an NHB claim beyond an optimized model-derived index.

## Reproducible explanatory pipeline

The new post-processing script
`human_study/scripts/analyze_nhb_explanations.py` analyzes the existing
71 calibrated complete human sessions without additional recruitment or
model inference. It produces private item/answer-by-wave diagnostics and
disclosure-checked, figure-ready aggregates in
`tex/Figures/nhb_explanatory/`.

Run instructions, the three analyses, privacy restrictions, curated
native-answer allowlist and Git push procedure are in
`human_study/reports/NHB_EXPLANATORY_ANALYSIS_README.md`.
Synthetic regression tests are in
`human_study/tests/test_analyze_nhb_explanations.py`.
The manuscript should be updated with quantitative statements and
additional panels **after** the investigator runs, verifies and commits
the actual aggregates. No explanation results are inferred from the
absence of data.
