# Exploratory 2018 model-conditional reference pole (not validated)

`gss_2018_partyid_contrast_opinion574.csv` is a preserved research
candidate **only**. It is not approved for the production DTAG ideology
index or for the question-set library.

Native experiment: GitHub Actions run 38913790951 on DTAG dev.
Model: gss/gss_2018 (public v0.2.1 GCS release).
Construction: for each of 574 predeclared, codebook-filtered opinion
variables, evaluate the GSS 2018 LSM conditional categorical response
distributions under partyid='strong democrat' and partyid='strong republican'.
Select each stratum's most overrepresented answer; retain only variables
with categorical total-variation distance >= 0.05.

Four items survived:

- conpress: TV 0.149899
- confed: TV 0.143910
- gunlaw: TV 0.078919
- goveqinc: TV 0.055479

The poles are **not observed average respondent profiles**; they are
contrastive categorical projections of two model-conditioned probability
distributions.

Native result (CM/WF only core anchors): CM +0.27308, WF -0.06828,
I(empty) +0.08092. While the example personas have opposite signs, this
alone is not evidence of correct political orientation. On the separately
specified seven-level polviews ordering, the proposed pole yielded
5 concordant / 6 discordant / 10 ties (adjusted concordance 0.476),
below the manually defined 38-item v2 pole's 12 concordant / 9
discordant / 0 ties (0.571).

This is a **negative validation result**, so do not adopt the candidate
pole. The file is committed only to make its exact construction and failure
reproducible. Full conditional probability tables and diagnostics can be
downloaded from the linked GitHub Actions run.

Other native construction experiments:
- Categorical modes on 38 items: 1 differing-mode item; inadequate.
- Conditional contrast on 38: 2 variables; CM/WF and polviews were tied.
- Polviews-extreme conditional contrast on 38: 0 variables; inadequate.
- Direct partial-state partyid anchors: gave extreme CM/WF signs by
  construction and is tautological with respect to partyid.

The proper next experiment requires actual GSS 2018 respondent microdata
and documented weights, not tuning modal/contrast thresholds until a
preferred persona sign is obtained.
