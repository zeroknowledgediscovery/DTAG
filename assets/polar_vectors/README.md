# Polar vectors

Place the actual `polar_vectors.csv` for the model family here, or pass it explicitly with `--polar_vectors`.

The required structure is one of:

```csv
variable,left,right
POLVIEWS,Liberal,Conservative
...
```

or long format:

```csv
variable,pole,value
POLVIEWS,left,Liberal
POLVIEWS,right,Conservative
...
```

The response labels must exactly match the support values in the trained qnet model.
The included `polar_vectors_template.csv` is only a structural template, not a valid analysis file.

## Wave-specific GSS poles

`polar_vectors.csv` is the canonical pole definition (one wording). GSS waves
differ in which items were asked and in how answers are labelled, so DTAG
resolves it per wave:

- `gss_pole_corrections.csv` documents every answer-label correction
  (e.g. `grass`: `legal` → `should be legal` in 2022+; `viruses`:
  `definitely true` → `true`), including one source error (`colmil` R was
  `not fired`, a `colcom` label; corrected to allow the militarist to teach).
- `scripts/build_gss_polar_vectors.py` checks the canonical poles against each
  wave's native model labels and writes `gss/gss_YYYY_polar_vectors.csv` for
  all 35 waves, plus `gss/pole_resolution_report.csv` (every item × wave
  decision) and `gss/README.md` (summary). GSS 2021 split-ballot items
  (`biblev`/`biblenv`, `grassv`/`grassnv`, …) are mapped to both versions.
- An item is kept only when both its L and R answers exist in that wave.
  Otherwise it is dropped from both poles and reported, never written.

At runtime, when a GSS model is used with the canonical file, DTAG switches to
that wave's file automatically, and it validates every pole pair against the
loaded model. Unrecognised answers are dropped and reported in the run's
metadata (`polar_vectors_summary.dropped_items`) and in the web app's ideology
details.

## Right-pole revision (v2)

The original right pole used several answers that only a small minority of
GSS respondents give, which placed the R pole far from the population and
pushed the model's average respondent (and most conservative personas) to a
negative index. The canonical R pole was revised with one rule, applied once
and used unchanged in every wave:

> A right-pole answer given by fewer than 15% of respondents (model marginal,
> averaged over GSS 2014, 2016, 2018, 2022 and 2024) moves one step toward
> the centre of its answer scale, never past the middle category. If no such
> answer exists (yes/no items), the item is dropped from both poles.

| Item | R (v1) | R (v2) | Share giving the v1 answer |
|---|---|---|---:|
| `natsoc` | too much | about right | ~6% |
| `natenvir` | too much | about right | ~10% |
| `pillok`, `pilloky` | strongly disagree | disagree | ~14% |
| `religcon`, `religint` | strongly disagree | disagree | ~3–4% |
| `abhlth` | no | dropped (both poles) | ~8% |

The left pole is unchanged. The previous definition is kept as
`polar_vectors_v1.csv` so earlier runs can be reproduced
(`--polar_vectors assets/polar_vectors/polar_vectors_v1.csv`; the wave-specific
switch applies only to the canonical `polar_vectors.csv`).

Effect on the ideology index (average respondent / conservative-male persona /
progressive-female persona, persona states fixed):

| Wave | v1 | v2 |
|---|---|---|
| 2014 | −0.117 / −0.058 / −0.192 | −0.039 / +0.017 / −0.126 |
| 2016 | −0.060 / −0.031 / −0.123 | +0.046 / +0.063 / −0.031 |
| 2018 | −0.057 / −0.045 / −0.083 | +0.060 / +0.071 / +0.027 |
| 2022 | −0.193 / −0.091 / −0.270 | −0.100 / −0.001 / −0.196 |
| 2024 | −0.138 / −0.054 / −0.251 | −0.052 / +0.020 / −0.196 |
