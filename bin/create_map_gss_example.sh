#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/make_map.py \
  --dta data/raw/GSS2024.dta \
  --codebook_pdf data/raw/GSS_2024_Codebook.pdf \
  --out maps/map2024.csv
