# DTAG theory-of-mind manuscript (IEEEtran working format)

This is a **working scientific manuscript**, not a completed PNAS submission.

## Build

From the repository root:

```bash
cd tex
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
```

or using the supplied Makefile: `make -C tex`. A full TeX Live installation with `IEEEtran`, `pgfplots`, `tikz`, `bibtex`, and associated packages is required.

Files:
- `main.tex` — IEEEtran two-column theoretical manuscript with TikZ schematic, **explicitly illustrative** mock figure, a hypothesis/experiment table, and a preregisterable Prolific study.
- `references.bib` — 24 bibliographic sources in BibTeX.
- `Makefile` — standard `latexmk` commands.

## Scientific status and submission direction

The existing DTAG outputs are computational conditioning trajectories; **they do not establish human persuasion**. Theoretical alternatives (passive phenotype refinement vs. reflexive construction) motivate prospective randomized testing. The five-arm Prolific study is **proposed**, not performed. The plots in Figure 2 are **synthetic mock illustrations** with arbitrary values, not predictions or measured results. The only quantitative prior-work results cited are identified as preliminary results from *The Fabric of Opinion*.

The current class is `IEEEtran` because it was explicitly requested as an authoring format. The manuscript's argument and significance statement are intended for eventual PNAS-style development, but class and submission requirements would need to be changed before submitting. PNAS is not being claimed as the current manuscript class.

### Study preregistration and IRB
Before recruitment: pilot and freeze stimuli, baseline anchors, unrelated held-out outcome battery, primary delayed AB vs BA contrast, missingness plan, hypotheses, sample size determined by power analysis, statistical code, and prospective model artifact identifiers. Obtain relevant institutional human-participants authorization and apply Prolific's longitudinal study / prescreening procedures. Do not report the sketch of study arms as a completed experiment.

### Open empirical tasks
1. Reproduce DTAG trajectories from a frozen GSS model, with random/information-gain/geometric policies, response modes and multiple seeds.
2. Run a held-out answer-prediction comparison against baseline models; report proper scores and calibration.
3. Test robustness to pole sets, waves, semantic mapping and conditional incompatibility.
4. Pilot the five-arm Prolific protocol; then power, preregister and run the main/longitudinal study.
5. Replace Figure 2's illustrative panels with measured results before preparing a submission.
