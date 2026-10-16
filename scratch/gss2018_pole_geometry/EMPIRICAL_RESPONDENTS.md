# GSS 2018 pole from actual respondent answers — fixed 42 variables

This work is independent from the political-question optimizer. It does not
change production pole files and does not filter pole variables according
to CM/WF effects.

## Verified Dropbox source

Full GSS 2018 respondent-level CSV, originally used for LSM experiments:

    /ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv

Usually synchronized locally as:

    ~/Dropbox/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv

Dropbox file size 11,045,695 bytes. A full-width smaller dataset was also
found under

    /ZED/Research/lsm/results/lsm_veritas/
      gss_2018_holdout_80_20/split/gss_2018_heldout20_raw.csv

That extract contains 357 respondents and all 1034 survey variables.
An older legacy 892-row analysis CSV has only 158 variables and is
NOT an adequate basis for all 42 pole items.

The full dataset is NOT committed or redistributed. The saved 357-row
file was a holdout split for a different project. Using it as a pole
pilot means it is no longer an independent holdout for this analysis.

## Fixed construction

Keep all 38 variables already defined in the 2018 manual pole, plus
these four predeclared topical additions:

    conpress eqwlth cappun goveqinc

Left group: partyid in {strong democrat, not str democrat, ind,near dem}.
Right group: partyid in {strong republican, not str republican, ind,near rep}.

For each variable, calculate the complete empirical categorical
distribution of survey responses by group, using respondent rows.
If a genuine numeric survey-weight column exists, use it. If weights
are encoded as letters (b,c,d, etc.) as in the native LSM CSV, report
the analysis as UNWEIGHTED instead of interpreting symbolic categories
as sampling weights.

Choose distinct representative answers by a prespecified balancing
rule based on each group's observed frequency and the intergroup
difference. All 42 variables are retained. When two groups have the
same mode and a nonmodal response must be selected to make distinct
poles, that choice is flagged in construction_audit.csv. If there are
insufficient usable responses, the canonical baseline answer is
retained with a disclosed fallback flag.

Because the answer categories are nominal, none of this should be
represented as taking a numeric mean of the answer label.

## Analyze the complete 2018 respondent CSV locally

From your DTAG checkout:

    git switch dev
    git pull --ff-only origin dev

    python scratch/gss2018_pole_geometry/derive_from_respondents.py

This builds a 75% development / 25% evaluation split of the full actual
respondent rows and writes:

    scratch/gss2018_pole_geometry/results/respondent_stratified_full/
      gss_2018_empirical_partyid_42_poles.csv
      construction_audit.csv
      empirical_partyid_marginals.csv
      heldout_associations.csv
      summary.json
      REPORT.md

On heldout respondent rows, check whether the 42 selected pole response
pairs still separate party identification, and whether they also show
consistent response patterns with independent polviews categories.
The seven-level ordered native model check is a separate experiment.

For native model geometry and additional respondent-row tests:

    python scratch/gss2018_pole_geometry/derive_from_respondents.py \
      --native-eval --max-native-respondents 50

The native test loads the proper GSS 2018 LSM through the same GCS
downloader as DTAG's web app, verifies all chosen response labels,
and compares against the official 38-item pole. For heldout row
evaluation, both partyid and polviews are removed from the conditioning
state so the evaluation target is not explicitly supplied as an input.
The native model itself may have already been trained on these survey
rows, so holdout means excluded from POLE CONSTRUCTION, not from
LSM training.

## Exploratory pilot from 357 observed respondent rows

The fixed file

    candidates/gss_2018_partyid_empirical42_probe357.csv

was made directly from the smaller full-width Dropbox respondent
extract. It contains 42 items and should be treated as a preliminary
candidate, not the final full-survey pole.

Its observed response patterns:
- All 42 contrasts were positive on the SAME partyid strata used to
  select them; that observation is in-sample and not an independent test.
- Across the same respondent sample stratified by polviews, 36 of 42
  contrasts aligned, while six had the opposite sign:
  godchnge, libmil, libmslm, religint, rowngun, spkmil.

These are descriptive signs only, not a statistical significance test
or evidence of causal political influence.

To validate this preliminary pole on the native GSS 2018 model:

    python scratch/gss2018_pole_geometry/test_empirical_candidate.py

Its seven-level category ordering and reference persona indexes can
then be compared to the original 38-variable v2 pole. The pilot output
does not replace any canonical assets.

## Interpretation

Distinguishing CM and WF with opposite signs is insufficient evidence
of a good ideological axis. Before promotion of any empirical pole,
evaluate category ordering in heldout observations, stability of
response pairs across random data splits and uncertainty, and whether
a hard categorical pole represents a plausible joint respondent profile.

Neither construction nor validation uses a survey question sequence,
attempts to alter participants' views, or optimizes persona movement.
