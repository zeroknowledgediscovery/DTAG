# GSS 2018 pole adequacy audit

Independent diagnostic. No question optimization and no changes to production poles.

## Static facts

Pole sizes: 2016=34, 2018=38, 2024=27.
2018/2024 overlap: 27 variables.
2018-only: abpoorw, colmil, comfort, godchnge, intmil, libhomo, libmil, religcon, religint, spkmil, viruses
Wave-dependent response labels: bible, colcom, grass, spkcom
Unresolved 2018 canonical item(s): prayfreq

The 2018 pole may be syntactically valid without its zero point being
substantively calibrated. Compare WF against I(empty), not just against zero.

## Native-model index (same model, different pole definitions)

| Pole variant | empty | CM_core | WF_core | CM_rich | WF_rich |
|---|---:|---:|---:|---:|---:|
| 2018_v2_all | +0.06005 | +0.07262 | +0.04441 | +0.08637 | +0.02426 |
| 2018_v1_all_resolved | -0.03696 | -0.02811 | -0.04731 | -0.01220 | -0.06690 |
| 2018_v1_matched_items | +0.00226 | +0.01152 | -0.01046 | +0.02723 | -0.03085 |
| 2018_v2_matched_items | +0.05863 | +0.07382 | +0.04245 | +0.08802 | +0.01991 |
| 2018_v2_common_with_2024 | +0.00702 | +0.02491 | -0.01192 | +0.04538 | -0.03405 |
| 2018_v2_without_viruses | +0.06072 | +0.07352 | +0.04480 | +0.09025 | +0.02163 |

## Interpretation

2018 v2 anchor monotonicity diagnostics: {"partyid": {"expected_labels": ["strong democrat", "not very strong democrat", "independent, close to democrat", "independent (neither, no response)", "independent, close to republican", "not very strong republican", "strong republican"], "n_pairwise_comparisons": 1, "not_found": ["not very strong democrat", "independent, close to democrat", "independent (neither, no response)", "independent, close to republican", "not very strong republican"], "pairwise_monotonicity_reversals_v2": 0, "tested_labels": ["strong democrat", "strong republican"], "unranked_model_labels": ["ind,near dem", "ind,near rep", "independent", "not str democrat", "not str republican", "other party"]}, "polviews": {"expected_labels": ["extremely liberal", "liberal", "slightly liberal", "moderate, middle of the road", "slightly conservative", "conservative", "extremely conservative"], "n_pairwise_comparisons": 6, "not_found": ["moderate, middle of the road", "slightly conservative", "extremely conservative"], "pairwise_monotonicity_reversals_v2": 2, "tested_labels": ["extremely liberal", "liberal", "slightly liberal", "conservative"], "unranked_model_labels": ["extrmly conservative", "moderate", "slghtly conservative"]}}

1. Verify an empty-state offset before interpreting the absolute sign.
2. Determine whether CM > WF even if both are positive.
3. Compare v1/v2 on the matched item set; do not confuse pole
   composition with answer-category changes.
4. Compare 2018 full 38-item pole with its 27-item common subset.
5. Inspect the effect of removing the science-knowledge item viruses.
6. Inspect leave_one_out.csv, recognizing that changes are nonadditive.
7. Check anchor_monotonicity.csv: does the 2018 index rise
   from liberal/Democratic to conservative/Republican survey labels?
8. Verify observations under core and rich states, and optional
   LLM-decoded cached states. A descriptive persona is not a population sample.

Do not revise canonical poles solely to make a chosen persona negative.
