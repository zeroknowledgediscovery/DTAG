# GSS qnet models

Copy GSS qnet model files here, for example:

- `gss_2022female.pkl.gz`
- `gss_2022male.pkl.gz`
- `gss_2016female.pkl.gz`
- `gss_2016male.pkl.gz`

For year-specific GSS models, do not force `--year` unless the model contains an explicit `A_YEAR` feature. The patched `pipeline6iloc.py` soft-skips hard year/geography forcing if those features are absent.
