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
