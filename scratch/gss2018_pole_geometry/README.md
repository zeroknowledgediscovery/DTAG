# GSS 2018: why does a liberal persona have a positive ideology index?

**Independent pole-geometry investigation.** This directory is deliberately
separate from optimizer/. It never changes the production pole files,
question selection, or saved optimizer trajectories.

## Preliminary findings from checked repository artifacts

A *positive* index is not the same thing as "the model thinks this person is
conservative." The actual DTAG definition is

    I(s) = [d(s_L,s) - d(s_R,s)] / d(s_L,s_R)

with s_L and s_R constructed from a collection of extremal survey answers.
This index has no guarantee that the average respondent, the empty state, or
every self-described liberal is below zero.

The published pole documentation in assets/polar_vectors/README.md already
reports the effect of changing the **right pole**, holding persona states fixed:

| GSS 2018 reference | Original right pole v1 | Revised right pole v2 |
|---|---:|---:|
| Average respondent | -0.057 | +0.060 |
| Conservative male | -0.045 | +0.071 |
| Progressive female | -0.083 | +0.027 |

The user's subsequent GSS 2018 LLM initialization gave CM +0.0661 and
WF +0.0288 under v2. Those numbers are compatible with the **previously
documented pole shift**. They are not, by themselves, evidence that the LLM
misread the liberal description. An independent runner bug separately caused
only one of polviews/partyid to be protected; that is being fixed in
optimizer/ and must be verified before comparing exact states.

The static 2018 pole file contains 38 item pairs, compared with 34 (2016)
and 27 (2024). All 27 variables used in the 2024 pole occur in the 2018
pole; 2018 adds 11:

    abpoorw colmil comfort godchnge intmil libhomo libmil
    religcon religint spkmil viruses

Four shared variables use different *answer wording* between 2018 and 2024:
bible, colcom, grass, spkcom. This is expected from survey coding changes,
not a demonstrated inversion.

The pole resolution log shows only one unresolved 2018 candidate, prayfreq,
which was dropped symmetrically because the requested right-side label is
not a model response option. The other 38 pairs were resolved to model
response labels, with documented corrections to colmil and viruses.
That establishes **syntactic validity**, not empirical ideological validity.

Items requiring a substantive review include viruses (knowledge about viral
biology, not a political attitude) and intmil, colmil, libmil and spkmil.
Opposite answers to free-speech questions about extremists need not load
uniformly on the left/right ideology axis. They are flagged for investigation,
not assumed wrong.

## Reproduce static checks (no model needed)

From the DTAG repository root:

    git switch dev
    git pull --ff-only origin dev
    python scratch/gss2018_pole_geometry/audit.py --static-only

Writes:

    scratch/gss2018_pole_geometry/results/static_summary.json
    scratch/gss2018_pole_geometry/results/wave_pole_inventory.csv
    scratch/gss2018_pole_geometry/results/v1_v2_changes.csv
    scratch/gss2018_pole_geometry/results/REPORT.md

## Native experiment: same 2018 model, different pole geometries

For exact native-model distances:

    python scratch/gss2018_pole_geometry/audit.py --skip-loo

Then, for the full leave-one-pole-item-out sensitivity:

    python scratch/gss2018_pole_geometry/audit.py

The model is installed if missing via scripts/fetch_models.py, the same
Google Cloud Storage downloader as the webapp, respecting DTAG_MODEL_ROOT
and DTAG_MODEL_RELEASE. The experiment uses canonical_map() for 2018 and
the wave's proper pole file. On a machine with the installed native model,
pass --no-download to disallow network downloads.

The audit fixes the **model at GSS 2018** while comparing:
- 2018 v2 (all 38 items)
- Original v1 resolved against 2018 native response labels
- v1 versus v2 with exactly the same pole-variable set, to isolate changed
  answer categories from changed coverage
- 2018 v2 restricted to its 27 variables shared with the 2024 pole
- 2018 v2 without the scientifically questionable viruses item
- Each v2 item removed in turn (full run without --skip-loo)

For each variant, it calculates I, d(state,L), d(state,R), d(L,R),
I(state)-I(empty), and displacement relative to the full 2018 v2 geometry.
The model states include empty, two political anchors for each of CM/WF,
and rich CM/WF historical reference states (only assignments accepted in
the native 2018 model). The first two anchors must be accepted or the audit
fails clearly rather than fabricating labels.

To additionally read the cached 2018 LLM-decoded initial states, if present:

    python scratch/gss2018_pole_geometry/audit.py --include-cached --skip-loo

Or specify an alternative cache:

    python scratch/gss2018_pole_geometry/audit.py --include-cached \
      --cached-personas /path/to/gss_2018_base_personas.json --skip-loo

The cached file must be a JSON list of participant records with an id and
state field. The failed earlier run may not have created a complete cached
base file.

Native outputs (all ignored by Git under results/):

    results/native_summary.json
    results/native_variants.csv
    results/anchor_monotonicity.csv
    results/leave_one_out.csv
    results/REPORT.md

Run review tests:

    python -m pytest -q optimizer/tests

## How to decide whether the pole is adequate

**Mechanical correctness:** all pole values are legal native model labels,
L/R assign different answers, and the runtime builds a finite, positive
d(L,R). The existing wave-specific resolution establishes most of this.

**Zero-point calibration:** measure I(empty), I(CM_core), I(WF_core) under
identical v1 and v2 geometries. If I(empty) is strongly positive and a
liberal persona is positive but shifted LEFT of the empty state, the sign
is acting as a poor proxy for human ideological self-identification.

**Independent orientation test:** the audit scans recognized response
labels of the 2018 native polviews and partyid items, ordered from
liberal/Democratic to conservative/Republican. It saves
anchor_monotonicity.csv and counts pairwise ordering reversals for v2.
If the index preserves the order despite being positive for the liberal
persona, the zero-point issue is more plausible. If labels order
incorrectly, the pole is not simply offset and needs stronger review.
The labels in the model that do not match the expected wording are listed
in native_summary.json rather than silently invented.

**Content validity:** the hand-chosen 38 survey questions must be justified
as indicators of a coherent single political orientation. Removing
nonideological or cross-cutting questions is a *sensitivity check*, not
automatically a justified correction.

**Robustness:** examine whether CM and WF are relatively ordered as
expected, and whether that ordering and their distance from the average
change when the polar specification changes. Do not compare absolute
I values across GSS years without accounting for the different trained
models, pole sets and response support.

**External calibration still needed:** anchored observations and empirical
survey strata labelled by polviews/partyid, ideally held out from pole
design, with monotonicity, group distributions, and uncertainty. A sign
threshold of zero should not be declared "liberal versus conservative"
until validated. The 2018 reference poles do NOT themselves include
polviews or partyid, so an empirical check is particularly important.

No source or pole files are altered by this experiment. Do not redefine
poles merely to force the reference liberal persona below zero.


## Construct a model-stratified GSS 2018 pole

The separate script derive_stratified_poles.py builds an exploratory pole;
it does not alter official files under assets/polar_vectors.

Default reference strata:

    partyid = strong democrat
    partyid = strong republican

For each 2018 pole variable it calculates the full categorical distributions
P(X_v = answer | partyid = strong democrat) and
P(X_v = answer | partyid = strong republican) using the native LSM.

**Important:** This is the model-implied conditional distribution, NOT a
weighted empirical frequency table from actual 2018 survey respondent rows.
The repository does not bundle raw microdata (see data/raw/README.md).

GSS categories are strings, so the script retains the full conditional
distributions. The first native modal-response experiment found that only
**one of 38** variables had different modal answers under the two strata
(GitHub Actions run 38912439101), which is insufficient for a stable pole.

The revised default uses **conditional contrasts**: it chooses the answer
most overrepresented among Democrats for L and the answer most
overrepresented among Republicans for R. These answers can differ even
when both groups share the same most likely answer. Responses are retained
when total variation exceeds --min-tv (default 0.05). The complete
probability distributions, group modes, selected contrast answers, and
conditional probability differences are saved in conditional_responses.csv.
Use --construction modal to reproduce the one-variable experiment.

This procedure does not use the CM/WF measured indices, political-shift
goals, or heldout orientation results to select pole variables or answers.
The constructed poles are **categorical association contrasts**, not
representative or average actual respondents.

Political anchor variables polviews and partyid are always excluded from
the candidate pole itself. The 2018 polviews response ordering is an
independently chosen *measurement criterion* for partyid-trained poles,
but it is NOT an external data holdout because the LSM was trained on
the same underlying GSS data.

Run:

    python scratch/gss2018_pole_geometry/derive_stratified_poles.py

For a quick initial run, omit one-at-a-time pole deletions:

    python scratch/gss2018_pole_geometry/derive_stratified_poles.py --skip-loo

An alternative, pretrained-model-conditioned design:

    python scratch/gss2018_pole_geometry/derive_stratified_poles.py \
      --stratify polviews --left "extremely liberal" \
      --right "extremely conservative" \
      --out scratch/gss2018_pole_geometry/results/model_stratified_polviews

This checks partyid ordering, rather than polviews ordering. For a broader
opinion-item candidate pool, add --pool opinion --max-items 150.

You may fix a *common* additional attribute in both strata, subject to
native response label validation, for example:

    python scratch/gss2018_pole_geometry/derive_stratified_poles.py \
      --fixed 'relig=protestant' \
      --out scratch/gss2018_pole_geometry/results/partyid_protestant

The output folder contains:

- gss_2018_model_stratified_poles.csv (variable,R,L; proposed trial poles)
- conditional_responses.csv (full conditional probabilities, modes, TV)
- persona_index_comparison.csv (existing v2 and proposed pole comparisons)
- anchor_orientation.csv (ordered polviews / partyid response indices)
- empirical_pole_leave_one_out.csv (sensitivity, if not --skip-loo)
- results.json and REPORT.md (measurement provenance and interpretation)

The script compares proposed and manually defined v2 poles on the same
2018 LSM, including a common-variable subset to control composition.
It reports absolute index, I-I(empty), and I-I(moderate). Opposite
signs for two hand-selected personas alone are not considered sufficient
evidence that a pole is valid. No survey question optimization is performed.

Uses optimizer.dtag_bridge.ensure_model and scripts/fetch_models.py, so a
new machine downloads missing native models from the same public GCS release
and cache as the DTAG webapp.
