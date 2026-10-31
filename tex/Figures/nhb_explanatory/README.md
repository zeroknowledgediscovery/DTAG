# Nature Human Behaviour explanatory results

This directory is the **only public output destination** for `human_study/scripts/analyze_nhb_explanations.py`.

The real 71-participant results are **not committed yet**. The investigator generates and reviews these aggregate CSVs locally from the restored, private analysis export before committing them. Do not populate this directory with synthetic fixtures or export raw participant-level records.

## Generated files

| CSV | Contents |
| --- | --- |
| `nhb_resistance_stage_metrics.csv` | Q1–4, Q5–20 and Q1–20 group mean signed displacement, 95% participant-bootstrap intervals, predicted-vs-observed summaries for all and single-assignment steps |
| `nhb_question_topics.csv` | Prespecified/heuristic GSS topic families by Right Q4 subgroup and stage; minimum disclosure threshold |
| `nhb_target_questions.csv` | Individual selected native GSS items selected by at least five people and at least eight question events |
| `nhb_predicted_observed_quintiles.csv` | Five event-ranked single-assignment prediction bins under Left or Right, with participant-cluster bootstrap intervals for observed step means |
| `nhb_right_q4_trajectories.csv` | Twenty-question trajectories (step 0–20) with bootstrap intervals for Right-push initially Left Q4-flagged (19), Right-push initially Left Q4-unflagged (10), and Right-push initially Right (9) |
| `nhb_curated_answer_categories.csv` | **Empty by default.** Populated only for respondent native categories explicitly reviewed in a local allowlist and meeting 5-person/8-event disclosure thresholds; no original native values written here |
| `nhb_manifest.json` | Schema version, completeness/coverage and output names |

No file in this directory should contain a participant identifier, raw/free-text answer, Prolific ID, timestamps, individual trajectory, or original unvetted native response values.

## Publication use

These are aggregate candidates for the DTAG Nature Human Behaviour draft `tex/dtag_main2.tex` and new Extended Data panels. After running, inspect the group differences and compare prediction coverage, scopes and multi-assignment rates **before** deciding what can be claimed in the paper. The script does not automatically revise the manuscript, generate conclusions, or commit anything.

### Statistical interpretation

- Q4 flag is based on movement through question four. Q5–20 differences between flagged and unflagged groups are descriptive and not independent prospective validation.
- The original randomized cohort and fixed-policy recruitment waves are not a single randomized policy comparison. Detailed wave splits are private.
- The LSM's prediction is for the selected target question; observed index changes can reflect multiple mapped answers. Single-assignment comparisons are more interpretable; neither proves persuasion or latent belief change.
- The public topic categories are exploratory dictionary/wording matches and should be audited against GSS question wording.
- Suppression of uncommon question/response cells may preclude publishing specific high-impact but infrequent items. The earlier 4-person Left-push table is a separate researcher-reported exploratory table.
- Public response labels require a separately reviewed allowlist and remain **associations with joint question steps**, not a causal attribution to an individual survey variable.
