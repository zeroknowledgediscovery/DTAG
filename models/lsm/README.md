# Native LSM model directory

Native C++ LSM models live under this tree. Legacy Quasinet `.gz` models remain
in their existing locations during migration.

Expected layout:

```text
models/lsm/
  gss/
    gss_2018/
    gss_2022/
    gss_2024/
  wvs/
    wvs7_pooled/
  afrobarometer/
    r1/
    ...
    r9/
  eurobarometer/
    ZAxxxx/
  anes/
  ces/
  ess/
  latinobarometro/
  arab_barometer/
```

Each trained model directory should contain native LSM runtime artifacts
(`source_maps/`, `trees/binary/`, `meta.txt`) plus DTAG's
`training_manifest.json`.

Use `scripts/train_native_lsm_models.py` rather than manually copying tree
fragments into this hierarchy.
