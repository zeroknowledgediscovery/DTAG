# Local survey source files

Raw survey datasets and source codebooks are intentionally not bundled with the
DTAG source repository.

Use this directory only as local staging when rebuilding maps or native LSM
models. Typical local inputs include `.dta`, `.sav`, `.csv`, and codebook
PDFs.

Do not commit source survey files unless their redistribution terms explicitly
permit it.

Relevant native tooling includes:

```text
scripts/dta_to_csv.py
scripts/build_gss_native_map.py
scripts/build_all_gss_native_maps.py
scripts/getmap_dtag.py
scripts/build_eurobarometer_maps.py
scripts/train_native_lsm_models.py
```

The tracked source repository contains code, configs, and semantic maps. Native
model binaries are kept separately and resolved through `DTAG_MODEL_ROOT`.
