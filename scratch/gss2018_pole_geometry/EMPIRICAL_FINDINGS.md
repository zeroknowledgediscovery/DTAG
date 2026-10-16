# GSS 2018 empirical 42-variable pole — preliminary measured result

This file records ACTUALLY EXECUTED calculations, not anticipated outcomes.

## Data

The complete respondent file has been identified via Dropbox at
/ZED/Research/MAGICS_research/survey/data/gss/gss_2018.csv
(11,045,695 bytes), but it was too large for Dropbox's extracted-text
interface. The preliminary candidate was derived from the separate
357-row, full-width respondent CSV located at
/ZED/Research/lsm/results/lsm_veritas/gss_2018_holdout_80_20/split/
gss_2018_heldout20_raw.csv (2,215,346 bytes).

This was an earlier holdout split for another experiment. For the
present 42-item pole experiment all 357 rows were used for exploratory
response-frequency analysis; thus it is NOT a statistically independent
holdout for the pole's development. The full-data script in
derive_from_respondents.py instead makes a fresh 75%/25% row split.

The trial fixes the entire original 2018 set of 38 pole items and adds
four predeclared survey questions (conpress, eqwlth, cappun, goveqinc).
It does not rank or delete items based on strength of association.

L group is strong/not-strong/lean-Democrat respondents. R group is
strong/not-strong/lean-Republican respondents. For each variable, we
chose a pair of distinct observed responses based on predeclared
frequency/contrast criteria with minimum group support. Sample
survey-weight columns were alphabetically encoded as categories,
not usable numeric weights; this particular preview is unweighted.

Candidate: candidates/gss_2018_partyid_empirical42_probe357.csv.

The same-data partyid association check was positive for all 42
items, as expected given how reference responses were constructed.
When re-stratified by self-reported polviews using the same sample,
36 item-level contrasts agreed in sign and six disagreed:

    godchnge libmil libmslm religint rowngun spkmil

These six need specific content review and replication in the full
sample. They were NOT discarded, preserving the 42-variable inventory.

## Native-model validation (completed successfully)

Run: https://github.com/zeroknowledgediscovery/DTAG/actions/runs/38918554282

The native GSS 2018 model was downloaded from the same GCS release
used by the webapp. All 42 candidate response pairs matched supported
native model labels. The fixed candidate was NOT adjusted after seeing
native evaluation results.

| Pole definition | I(empty) | I(CM_core) | I(WF_core) | CM - WF |
|---|---:|---:|---:|---:|
| Current manual v2, 38 items | +0.06005 | +0.07262 | +0.04441 | +0.02821 |
| Empirical probe, 42 items | -0.19436 | -0.17030 | -0.20862 | +0.03832 |
| Empirical probe, shared 2024 items | -0.21851 | -0.18870 | -0.23015 | +0.04145 |

Note the sign of the new pole's empty-state index. Both CM/WF still
have negative absolute indexes with the 42-item pole. CENTERING on
I(empty) gives approximately CM +0.02406 and WF -0.01426. Thus merely
finding opposite absolute signs is not a suitable construction target.

### Seven-category native-model orientation checks

The two tests condition the native model on ONE response (polviews or
partyid), compute the resulting index, and compare the ordered response
categories. There are 7 categories = 21 pairwise comparisons each.

| Pole definition | polviews concordant / discordant | partyid concordant / discordant |
|---|---|---|
| Manual v2, 38 | 12 / 9 | 19 / 2 |
| Empirical probe, 42 | 16 / 5 | 18 / 3 |
| Empirical probe, 2024 shared | 15 / 6 | 19 / 2 |

No ties were observed in these three native-model checks. These are
model-geometry diagnostics, not heldout respondent performance.

Interpretation: the new actual-response pilot is somewhat better on
the native seven-level ideology ordering and roughly comparable on
party identification. But its pole origin changes substantially,
and it has been fitted from a relatively small respondent extract.
That is sufficient to justify a full-data validation, NOT to declare
the new pole generally superior.

## Next reproducible step — run full respondent experiment locally

The full source is already known and directly accessible in the user's
synchronized Dropbox. From the DTAG root:

    git switch dev
    git pull --ff-only origin dev
    python scratch/gss2018_pole_geometry/derive_from_respondents.py \
      --native-eval --max-native-respondents 50

The output summary.json, construction_audit.csv,
empirical_partyid_marginals.csv, heldout_associations.csv,
native_holdout_metrics.csv, native_respondent_holdout_indices.csv,
and REPORT.md give the full-data answer.

For native respondent-row evaluations, the classifier/index removes
both partyid and polviews from the input state to prevent direct
target leakage. Native test respondents are held out from POLE
CONSTRUCTION only; the previously trained LSM may already have seen
them, so model-training independence is not established.

No production pole files have been changed, and the rejected
four-item model-conditional pole from the earlier experiment remains
separately archived as a negative scientific result.
