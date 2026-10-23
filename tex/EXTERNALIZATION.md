# DTAG paper: standard pdfLaTeX compilation

The complete manuscript source is:

`tex/DTAG_full_manuscript_20q_colorbar.tex`

The canonical **case-sensitive** layout is:

```text
tex/
  DTAG_full_manuscript_20q_colorbar.tex
  references.bib
  Figures/
    publication_metadata.csv
    optimization_report.json
    pub_endpoint_*.csv
    pub_trajectory_*.csv
    pub_order_*.csv
    heatmap_*.csv
    External/                 # optional externalized TikZ vector PDFs
```

The 20-question publication CSVs are committed under \`tex/Figures/\`
and can be read directly after a normal \`git pull\`. No data symlink,
LuaLaTeX, preprocessing step, or custom compilation script is necessary.

## Standard compile command

From the repository root:

```bash
git switch experiment-integrated-10q
git pull --ff-only origin experiment-integrated-10q
cd tex
pdflatex -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
bibtex DTAG_full_manuscript_20q_colorbar
pdflatex -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
pdflatex -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
```

When invoked without full shell escape, TikZ plots are rendered inline.
The resulting PDF is \`tex/DTAG_full_manuscript_20q_colorbar.pdf\`.

## Optional fast builds with TikZ externalization

To create (or update) cached plot PDFs under \`tex/Figures/External/\`,
use the **standard pdfLaTeX executable** with \`-shell-escape\`:

```bash
cd tex
pdflatex -shell-escape -interaction=nonstopmode -halt-on-error DTAG_full_manuscript_20q_colorbar.tex
```

The document selectively externalizes four pictures: the integrated circuit,
endpoint plot, trajectories, and the consolidated Figure 2. Figure 2 contains
exactly two complete 3-by-6 PGFPlots groups (18 heatmaps and 18 order-effect
subpanels) within one named vector picture, \`dtag-figure2-panels\`.
Each picture gets a stable PDF filename in \`Figures/External/\`.
A normal \`pdflatex\` command works without enabling shell escape and
does not depend on those cache PDFs being present.

## Future completed experiments

The manuscript reads filenames defined by \`\\def\` macros before its
figures. To compile plots for another **completed** experiment, copy or
regenerate the publication CSVs into \`tex/Figures/\`, including
\`publication_metadata.csv\`. The source has no hard-coded experimental
values and uses no external included TeX figure snippets.

For generating plotting CSVs from finished native data, use
\`experiments/persona_push/publication_pgfplots.py\` with
\`--out tex/Figures\`; provide \`question_index.csv\` (from question
optimization) when the generator needs to infer active question IDs.
The generator is separate from compilation and does not rerun the native
model. Alternatively, \`scripts/ensure_publication_metadata.py tex/Figures\`
can reconstruct the metadata CSV from already generated plots.

**Note:** If you previously used a local lowercase \`tex/figures\`
symlink, it is no longer needed. \`tex/Figures\` is now the only
publication data directory.
