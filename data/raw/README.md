# Raw survey files

Raw survey datasets and codebooks are intentionally **not bundled** with the DTAG release candidate.

Use this directory only as a local working location when rebuilding maps or models. Typical local inputs include `.dta`, `.sav`, `.csv`, and codebook PDFs.

Do not commit source survey files unless their redistribution terms explicitly permit it.

Relevant map-building utilities include:

```text
scripts/make_map.py
scripts/getmap_dtag.py
```

The public runtime uses the trained artifacts and maps under `models/` and `maps/`.
