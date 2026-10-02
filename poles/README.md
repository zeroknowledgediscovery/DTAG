# Empirical pole discovery

This directory discovers **survey-native polar axes** from the LSM geometry.

GSS already has curated ideological poles under `assets/polar_vectors/gss/`.
Those remain the preferred GSS definition.  The workflow here is for surveys
where no externally justified left/right ideological axis exists.

## Definition

For one survey/model wave:

1. Draw `m` actual respondent rows from the data used to train the native LSM.
2. Convert each sampled row to a native-LSM state, retaining only response
   labels that are in that model's source-map support.
3. Compute the full pairwise LSM `qdistance` matrix.
4. Cluster the distance matrix with **k-medoids/PAM**, not k-means.  The default
   model is `k=2`; `k=3` is computed only as a structural diagnostic.
5. Use the two `k=2` medoids as empirical poles.  Because medoids are sampled
   respondents, the poles remain on the observed data manifold.
6. Define the polar index
   ```
   I(x) = [d(P_minus,x) - d(P_plus,x)] / d(P_minus,P_plus)
   ```
   which is the same geometry already used by DTAG's ideology index.  Thus
   `P_minus -> -1` and `P_plus -> +1`.

For generic surveys the two poles are **not called left/right**.  Their sign has
no political meaning unless an external orientation is supplied.  The
`variable,L,R` output uses DTAG's legacy polar-vector storage convention only:
`L == P_minus`, `R == P_plus`.

## Why medoids

The LSM geometry is metric but not assumed Euclidean.  Means/centroids can
therefore be undefined and can also create impossible synthetic respondents.
K-medoids operates directly on the qdistance matrix and returns actual sampled
rows.

## Diagnostics

A pole pair should not be accepted merely because two clusters can always be
fit.  The discovery script records:

- average silhouette for k=2 and k=3;
- cluster sizes;
- inter-pole qdistance;
- within-cluster mean distances;
- per-row number of valid observed responses;
- high-cardinality sampled variables, so administrative IDs/missingness can be
  detected before a pole pair is promoted.

The default product is always two poles.  A substantially stronger k=3
silhouette is a warning that the survey geometry may not be well described by
one axis; it is not automatically converted into three poles.

## Usage

Build the bundled native runtime first:

```bash
bash scripts/build_native_bindings.sh
```

Then, for one survey wave, specify the public DTAG model key:

```bash
python poles/discover_poles.py \
  --model-key afrobarometer/r5 \
  --out poles/results/afrobarometer/r5 \
  --sample-size 256 \
  --seed 1
```

The normal workflow deliberately uses the same sources as DTAG itself:

- **Model:** `scripts/fetch_models.py` resolves the public release manifest and
  downloads/verifies the native model from the DTAG GCS bucket if it is not
  already installed locally.
- **Data:** the corresponding training CSV is resolved from the locally synced
  Dropbox tree `~/Dropbox/ZED/Research/MAGICS_research/survey/data`.
  Set `MAGICS_RESEARCH_DATA_ROOT` (or pass `--data-root`) only if the local
  Dropbox mount is elsewhere.

Known automatic data mappings include:

- `gss/gss_YYYY` -> `survey/data/gss/gss_YYYY.csv`
- `afrobarometer/rN` ->
  `survey/data/afrobarometer/merged_csvs_lsm/merged_rN_data.csv`
- WVS7 -> the cleaned Wave 7 CSV under `survey/data/wvs_cleaned/`
- `eurobarometer/ZAxxxx` -> the matching `ZAxxxx_*.csv` in
  `survey/data/eurobarometer/`

`--model` and `--data` remain available only as explicit local overrides.

Outputs:

- `distance_matrix.npy`: qdistance matrix for the sampled respondents.
- `sample_assignments.csv`: sampled source rows, cluster assignment, distances
  to the two poles, and polar index.
- `medoids.csv`: the two full medoid respondent states.
- `polar_vectors.csv`: the symmetric pole representation accepted by DTAG.
  Only variables observed and valid on both medoids are included.
- `summary.json`: clustering, separation, label-validation, and
  high-cardinality diagnostics.

Do not commit large distance matrices or sampled respondent data.  Promote only
reviewed `polar_vectors.csv` files and compact metadata into
`assets/polar_vectors/<survey>/`.

## Orientation across waves

The first empirical pole pair in a survey family has arbitrary sign.  Across
subsequent waves the sign should be aligned to the previous accepted pair (or
to an external substantive anchor) before longitudinal polar-index plots are
interpreted.  This is an orientation problem, not a clustering problem.

## Acceptance rule

At minimum, inspect silhouette, cluster balance, pole separation, observed-data
coverage, and whether cluster membership is driven by administrative IDs or
missingness.  If the split is mostly missingness or a high-cardinality
identifier, clean/retrain the survey LSM before accepting the poles.

For backward convenience, `afrobarometer/merged_rN` is accepted as an alias for the public GCS key `afrobarometer/rN`.
