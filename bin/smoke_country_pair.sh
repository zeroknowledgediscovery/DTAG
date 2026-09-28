#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DTAG_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DTAG_ROOT"

QUESTION="${1:-Do you trust the government?}"

python3 scripts/test_country_conditioning.py

python3 scripts/interactive.py \
  --profile afrobarometer_r5_nigeria \
  --question "$QUESTION" \
  --logs_dir outputs/smoke_country_nigeria \
  --tag smoke_country_nigeria

python3 scripts/interactive.py \
  --profile afrobarometer_r5_ghana \
  --question "$QUESTION" \
  --logs_dir outputs/smoke_country_ghana \
  --tag smoke_country_ghana

python3 - <<'PY'
import json
from pathlib import Path

runs = {
    'Nigeria': Path('outputs/smoke_country_nigeria'),
    'Ghana': Path('outputs/smoke_country_ghana'),
}
resolved = {}
for country, folder in runs.items():
    metas = sorted(folder.glob('*.meta.json'), key=lambda p: p.stat().st_mtime)
    if not metas:
        raise SystemExit(f'FAIL: no metadata generated for {country}')
    meta = json.loads(metas[-1].read_text())
    forced = meta.get('forced_assignments', {})
    geo = meta.get('geography', {})
    var = geo.get('categorical_country_feature')
    val = geo.get('categorical_country_value')
    if not var or forced.get(var) != val:
        raise SystemExit(f'FAIL: {country} was not deterministically forced: {forced} / {geo}')
    resolved[country] = (var, val)
    print(f'{country}: {var}={val}; mode={geo.get("geography_conditioning_mode")}')

if resolved['Nigeria'][0] != resolved['Ghana'][0]:
    raise SystemExit('FAIL: country pair used different categorical features')
if resolved['Nigeria'][1] == resolved['Ghana'][1]:
    raise SystemExit('FAIL: country pair resolved to identical country values')
print('PASS end-to-end Nigeria/Ghana country localization')
PY
