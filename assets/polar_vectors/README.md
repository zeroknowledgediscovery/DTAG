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
