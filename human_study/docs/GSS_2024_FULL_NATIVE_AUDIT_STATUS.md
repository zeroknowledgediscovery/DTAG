# Full native GSS 2024 wording inventory — 2026-10-26

The complete [audit run](https://github.com/zeroknowledgediscovery/DTAG/actions/runs/40343248085) uses the actual v0.2.1 model and the original 2024 GSS release-2 codebook. Download the 811-row JSON and CSV from the `gss2024-811-native-variable-audit` artifact on that run.

| Metric | Count |
|---|---:|
| Actual native model variables enumerated | 811/811 |
| Variables matched to model semantic map | 811/811 |
| Official R2 codebook entries located | 781/811 |
| Source-specific standalone wording contracts | 155/811 |
| Variables with no native response support | 0 |
| Native variables absent from the R2 codebook extraction | 30 |

The previously confirmed 21 incomplete contexts now have source-specific contracts, including ranking, immigration alternatives, polling and confidence prompts, and 0–100 rating instructions. The latest live defects are also addressed: RINCOM16 has all 26 earnings categories; RACECEN3/RACERANK3 describe applicability and display the categories actually supported by the native model.

This is a complete **coverage inventory**, not complete manual certification of all respondent-facing prompts. A codebook label can still omit an interviewer card, a conditional stem, or alternate responses. All 811 rows are marked pending independent source-form validation; many model variables are metadata or respondent descriptors rather than candidate opinion questions. No native variables were removed, and dynamic scoring is unchanged.

See `human_study/scripts/audit_all_native_gss_2024.py` for reproduction and per-variable documentation and answer-alphabet verification.