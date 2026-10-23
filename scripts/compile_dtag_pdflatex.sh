#!/usr/bin/env bash
# Build DTAG with pdfLaTeX and selectively externalized figures.
# Usage: bash scripts/compile_dtag_pdflatex.sh [RUN_DIR] [--refresh] [--replot]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="${DTAG_RUN_DIR:-$ROOT/experiments/persona_push/runs/test_q3_r2}"
REFRESH=0
REPLOT=0
for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
    --replot) REPLOT=1 ;;
    --help|-h) echo "Usage: bash scripts/compile_dtag_pdflatex.sh [RUN_DIR] [--refresh] [--replot]"; exit 0 ;;
    *) RUN="$arg" ;;
  esac
done
[[ "$RUN" = /* ]] || RUN="$ROOT/$RUN"
RUN="$(realpath "$RUN")"
FIG="$RUN/figures"
TEX="$ROOT/tex"
CACHE="$TEX/Figures/External"
MAIN=DTAG_full_manuscript_20q_colorbar
[[ -f "$FIG/optimization_report.json" ]] || { echo "Missing $FIG/optimization_report.json" >&2; exit 2; }
mkdir -p "$CACHE"
# CSVs use lowercase tex/figures/; uppercase Figures/External/ caches rendered PDFs.
if grep -Fq '{\DTAGFigureDir}{Figures}' "$TEX/$MAIN.tex"; then
  echo "Incorrect plot path: TeX uses Figures/ (cache), expected figures/ (CSV data)." >&2
  echo "Use \providecommand{\DTAGFigureDir}{figures} in $MAIN.tex." >&2
  exit 2
fi

if [[ -e "$TEX/figures" && ! -L "$TEX/figures" ]]; then
  echo "tex/figures is an existing real directory; move it before using this builder." >&2
  exit 2
fi
OLD="$(readlink "$TEX/figures" 2>/dev/null || true)"
if [[ "$OLD" != "$FIG" ]]; then
  REFRESH=1
  ln -sfn "$FIG" "$TEX/figures"
fi
if [[ "$REPLOT" == 1 ]]; then REFRESH=1; fi
if [[ "$REPLOT" == 1 ]]; then
  read -r STEPS REPS < <(python3 - "$FIG/optimization_report.json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
print(x['steps'],x['reps'])
PY
)
  python3 "$ROOT/experiments/persona_push/publication_pgfplots.py" \
    --adaptive-endpoints "$RUN/adaptive/endpoints.csv" \
    --trajectory-ci "$RUN/adaptive/trajectory_ci.csv" \
    --order-endpoints "$RUN/order/run_endpoints.csv" \
    --steps "$STEPS" --reps "$REPS" --out "$FIG"
fi
python3 "$ROOT/scripts/ensure_publication_metadata.py" "$FIG"
if [[ "$REFRESH" == 1 ]]; then
  find "$CACHE" -maxdepth 1 -type f -name 'dtag-*' -delete
fi
cd "$TEX"
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error "$MAIN.tex"
bibtex "$MAIN"
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error "$MAIN.tex"
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error "$MAIN.tex"
echo "Manuscript: $TEX/$MAIN.pdf"
echo "Externalized figures: $CACHE"
