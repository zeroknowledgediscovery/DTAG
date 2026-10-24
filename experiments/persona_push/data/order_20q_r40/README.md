# Archived native GSS 2024 20-question order experiment: summary files

These are exact summary exports from the completed local DTAG run stored in
Dropbox at `experiments/persona_push/runs/test_q3_r2/`. **The directory
name is stale:** its `order/manifest.json` confirms 20 questions per
trajectory, 40 repetitions, 2,880 replay trajectories, and seed 20261021.

Included are adaptive displacement estimates, absolute fixed-order endpoint
means and their bootstrap confidence intervals, and matched contrasts for
original versus reverse/shuffles. The full 2,880-row native run endpoints and
individual question draws remain in the original run directory; those are
**not needed** to reproduce the summary estimates or plot.

Postprocess without any native model, data download, or question simulation:

```bash
python experiments/persona_push/order_absolute_from_saved.py
```

Outputs: `postprocess/absolute_order_displacements.csv`,
`postprocess/order_drift_report.json`,
`postprocess/absolute_order_displacements.pdf` and `.png`.

**Interpretation:** The confidence intervals were computed in the original
completed experiments and are reused verbatim. This analysis does not
independently recompute bootstraps or justify causal inference in humans.
The fixed original/reverse/shuffle trials are fresh conditional draws from
the same frozen item sets; they are not adaptive query selection. The
baseline matches between these saved adaptive and fixed-order summaries.

Computed comparison tables (no native LSM calls) are also stored in
`postprocess/absolute_order_displacements.csv` and
`postprocess/order_drift_report.json`. They were generated from the
archived summary files above.
