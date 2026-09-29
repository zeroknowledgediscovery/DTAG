# Native LSM model store

DTAG uses native C++ LSM models only.

The model corpus is intentionally not committed to Git. By default DTAG looks
under this directory, but production/development installs should normally keep
the model store outside the checkout and set:

```bash
export DTAG_MODEL_ROOT=/path/to/dtag/models
```

The model root contains family directories directly:

```text
$DTAG_MODEL_ROOT/
  gss/              # 35 models
  afrobarometer/    # 9 models
  wvs/              # wvs7_pooled
  eurobarometer/    # 207 ZA models
```

Each model directory must contain at least:

```text
source_maps/
trees/binary/
```

Current validated inventory: 252 native models.

Use:

```bash
python3 scripts/inventory_native_models.py
python3 scripts/audit_native_maps.py --deep
```

to validate an installed model store.

Large model artifacts are expected to be distributed separately from Git,
ultimately through the versioned private DTAG model store.
