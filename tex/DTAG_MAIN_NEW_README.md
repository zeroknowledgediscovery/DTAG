# Updated DTAG human-study manuscript

The original manuscript tex/DTAG_main.tex and its 49-session figure CSVs
are deliberately unchanged.

New files:
- tex/dtag_main_new.tex: revised complete manuscript and abstract.
- tex/humanstudy_new.tex: all 71 calibrated completed sessions, Q4 criterion,
  stratified success table, and Q4 confusion matrix.
- tex/Figures/humanstudy_figures_new.tex: same-style bold-axis trajectories
  and endpoint confidence intervals (from new 71-session CSVs).
- tex/Figures/humanstudy_resistance_figures_new.tex: two new response and
  resistance panels using verified public aggregate source CSVs.
- human_study/scripts/render_humanstudy_new_pgfplots.py: archives -> new
  aggregate CSVs, bootstrap intervals and generated endpoint table.

The new manuscript cannot yet compile with the updated trajectory panels
until private-session post-processing is performed. On the investigator's
machine, from the DTAG root:

~~~bash
git fetch origin experiment/prolific-human-study
git restore --source=origin/experiment/prolific-human-study --worktree -- \
  tex/dtag_main_new.tex tex/humanstudy_new.tex \
  tex/Figures/humanstudy_figures_new.tex \
  tex/Figures/humanstudy_resistance_figures_new.tex \
  tex/Figures/humanstudy_new_success_left.csv \
  tex/Figures/humanstudy_new_success_right.csv \
  tex/Figures/humanstudy_new_q4_correct.csv \
  tex/Figures/humanstudy_new_q4_errors.csv \
  human_study/scripts/render_humanstudy_new_pgfplots.py

python3 human_study/scripts/render_humanstudy_new_pgfplots.py \
  --analysis-dir "$HOME/private/dtag-analysis-2026-10-30-restored" \
  --output-dir tex/Figures --bootstrap 5000 --seed 20261030

cd tex
latexmk -pdf -interaction=nonstopmode -halt-on-error dtag_main_new.tex
~~~

For a restored cross-machine snapshot, use
--analysis-dir "$HOME/private/dtag-portable-2026-10-30-restored-v1/snapshot/analysis".

The generator verifies the complete calibrated arm totals (21 Left,
38 Right, 7 Neutral, 5 Random), baseline signs, endpoint directional
successes (20/21 and 21/38), and Q4 resistance classifier (TP17, FP2,
FN0, TN10). It excludes the separately recruited zero-calibration
Right cohort. It produces only public-safe aggregate outputs in
tex/Figures/humanstudy_new_*.csv and humanstudy_new_table.tex.
After verification, commit these newly generated aggregate files to
freeze the final plotting data. NEVER commit participant-level CSVs.

Old 49-session endpoint means and confidence intervals cannot be
reused. The new manuscript fails clearly if the updated endpoint
table has not been regenerated. The Q4 response/resistance PGFPlots
panel is already based on verified aggregate counts and has received
an independent LaTeX compilation smoke test; the entire revised
paper still requires the above workstation build.
