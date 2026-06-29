# Map files

These files map survey variables to question/label text used by the DTAG semantic layer.

Included maps were copied from the existing DTAG package:

- `map2022.csv`
- `map20162020.csv`
- `map.csv`
- `wvs7_variable_question_map.csv`

To regenerate a GSS map from a DTA file and codebook PDF:

```bash
python3 scripts/getmap.py \
  --dta data/raw/GSS2024.dta \
  --codebook_pdf data/raw/GSS_2024_Codebook.pdf \
  --out maps/map2024.csv
```
