# Build the DTAG manuscript with pdfLaTeX

The manuscript \`tex/DTAG_full_manuscript_20q_colorbar.tex\` is a complete
single source with no included figure .tex files. It reads the finished
experiment's external CSVs and \`publication_metadata.csv\` using PGFPlots.

The TikZ externalization setup follows the selective enable/disable pattern
in \`main_twin.tex\` / \`preamble.sty\` supplied for reference.

## Input path and figure cache (Linux is case-sensitive)

The TeX source uses **`tex/figures/`** (lowercase) for completed-run CSVs.
The build script creates `tex/figures` as a link to the selected run's
`figures` folder and automatically generates `publication_metadata.csv`
from the other published plot tables. **`tex/Figures/External/`** (capital F)
is reserved for cached vector figure PDFs; it does not hold data CSVs.

Run **`bash scripts/compile_dtag_pdflatex.sh`** from the repository root
rather than invoking `pdflatex` manually on a clean checkout. If an older
local TeX edit says `\\providecommand{\\DTAGFigureDir}{Figures}`, change it
to `\\providecommand{\\DTAGFigureDir}{figures}` before compiling.

## Commands

From the DTAG repository root:

```bash
git fetch origin
git switch experiment-integrated-10q
git pull --ff-only origin experiment-integrated-10q
bash scripts/compile_dtag_pdflatex.sh
```

For any other finished run (same CSV schema):

```bash
bash scripts/compile_dtag_pdflatex.sh experiments/persona_push/runs/new_q20_r40 --replot
```

After editing figure styling, rebuild the cached PDFs with:

```bash
bash scripts/compile_dtag_pdflatex.sh --refresh
```

You may also run manually from \`tex/\`, after the CSV link exists:

```bash
mkdir -p Figures/External
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
bibtex DTAG_full_manuscript_20q_colorbar
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
```

## Design

- \`tex/Figures/External/\` receives **nine** named vector-PDF caches:
  the circuit, endpoints, six-persona trajectories, and six row-wise
  heatmap/order-effects combinations.
- The six-row split is deliberate: pdfTeX has more restrictive memory limits
  than LuaTeX. Individual rows preserve the original 18 square heatmaps,
  six-persona order comparisons and the shared question-index colorbar.
- Externalized figures are created with \`-shell-escape\`, then reused by
  subsequent compilations without shell escape if inputs are unchanged.
- The builder links \`tex/figures\` to the selected run's \`figures\` folder,
  ensuring externalizer subprocesses see the same paths. Changing runs
  automatically invalidates the cache.
- The generator \`experiments/persona_push/publication_pgfplots.py\` writes
  \`publication_metadata.csv\` from finished numerical results. Replotting
  does not rerun a stochastic/native experiment.
- The Figure filenames are defined as TeX macros above each figure.
  No numeric experimental outcomes are hardcoded in plot commands.

Do not compile legacy \`tex/main.tex\` for the 20-question document.
