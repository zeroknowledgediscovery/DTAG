# DTAG calibrated human experiment: Q4 baseline-relative resistance results

**Snapshot:** 2026-10-30 (post-archive recovery). **Population:** 59 GCS-archived 20/20 adaptive-question sessions in calibrated Left/Right arms (21 Left push, 38 Right push). Original randomized and fixed Left/Right follow-up studies are included. Neutral, Random and zero-calibration cohorts are excluded from this table.

Results below were transcribed from the investigator's completed private run of [`score_q4_right_resistance.py`](../scripts/score_q4_right_resistance.py) on the refreshed GCS-backed export. They have **not** been rerun from private data in GitHub. No participant-level records or Prolific identifiers are included in this repository snapshot.

## Directional and resistance-aware performance

| Initial inferred index | Left: moved left by Q20 | Right: moved right by Q20 | Right: moved right OR correctly identified resistance at Q4 |
|---|---:|---:|---:|
| Initially Left (`I0 < 0`) | **16/17 (94.1%)** | **12/29 (41.4%)** | **29/29 (100.0%)** |
| Initially Right (`I0 > 0`) | **4/4 (100.0%)** | **9/9 (100.0%)** | **9/9 (100.0%)** |
| **Overall** | **20/21 (95.2%)** | **21/38 (55.3%)** | **38/38 (100.0%)** |

Definitions: `I0` is the model-inferred index after six calibration questions, and `I4`/`I20` are indices after 4/20 adaptive questions. Success of Right push is `I20 - I0 > 1e-10`; success of Left push is `I20 - I0 < -1e-10`. For initially Left-leaning participants assigned Right push, early resistance is flagged when the **mean rightward movement through Q4** satisfies `(I4-I0)/4 <= 0` (using the script's `1e-10` tolerance). A correct Q4 resistance identification requires that the participant has `I20-I0 <= 1e-10`. Extended Right success means directional Right success **or** correctly identified Q4 resistance.

## Q4 resistance prediction (initially Left, Right push; n=29)

| Metric | Value |
|---|---:|
| Flagged resistant at Q4 | 19/29 |
| No net rightward movement by Q20 | 17/29 |
| True positives | 17 |
| False positives | 2 |
| False negatives | 0 |
| True negatives | 10 |
| Precision | **17/19 (89.5%)** |
| Sensitivity | **17/17 (100.0%)** |
| Specificity | **10/12 (83.3%)** |
| Classification accuracy | **27/29 (93.1%)** |

The reported **38/38 extended success** is a *combined outcome* (Rightward movement or correctly flagged endpoint resistance), not a claim that the Right intervention itself produced rightward movement in all 38 participants. The primary classifier target here is **baseline-relative response at Q20**, not Q4-to-Q20 incremental movement. These are model-inferred survey phenotypes, not verified political belief changes.

**Machine-readable aggregates:** [stratified CSV](q4_resistance_2026-10-30_stratified.csv) and [diagnostics JSON](q4_resistance_2026-10-30_diagnostics.json).
