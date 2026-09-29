# DTAG semantic maps

DTAG tracks semantic maps in Git. The native model feature list is authoritative:
every model feature must have a map row, even when the only available semantic
fallback is the native variable name.

Current validated inventory:

```text
maps/gss/                    35 GSS maps
maps/afromap/                 9 Afrobarometer maps
maps/wvs7_variable_question_map.csv
maps/eurobarometer/          207 Eurobarometer maps
```

Total: 252 maps for 252 native models.

Canonical audit:

```bash
python3 scripts/audit_native_maps.py --deep
```

Regenerate the complete map surface:

```bash
python3 scripts/complete_native_maps.py
```

Family-specific builders:

```bash
python3 scripts/build_all_gss_native_maps.py --force

python3 scripts/getmap_dtag.py   --codebook_pdf /path/to/afrobarometer_codebook.pdf   --model "$DTAG_MODEL_ROOT/afrobarometer/r9"   --out maps/afromap/afrobarometer_r9_map.csv

python3 scripts/build_eurobarometer_maps.py --za ZA7575

python3 scripts/build_eurobarometer_fallback_maps.py --report-only
```

Eurobarometer fallback maps retain explicit provenance. Unresolved variables are
kept as native-name fallbacks rather than assigned unverified semantics.
