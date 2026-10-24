# GSS 2024 source-wording audit — human-study instrument

Date: 2026-10-24. Branch: `experiment/prolific-human-study`.

**Status: BLOCKED for a verified, complete-question instrument.** This is a source inventory and missing-data report, **not** a substitute for full questionnaire text. No wording has been reconstructed or inferred.

## Source files actually checked

- `human_study/config/study.example.yaml`: 13 baseline, 28 adaptive, 3 outcomes; generated with `reviewed: false`.
- `maps/gss/gss_2024_map.csv`: rows use `question_text_filled`; the affected adaptive items are marked `YEAR_CODEBOOK` and provide `codebook_page` except `workhard` and `helpoth`.
- `maps/gss/gss_2021_map.csv`, `gss_2022_map.csv`, and `gss_2018_map.csv`: comparison only; earlier-wave text does not prove identical GSS 2024 wording.
- `human_study/backend/human_study/instrument.py`: copies the native adapter's `ctx.var_map[v]` directly to `original_wording`; regenerating the instrument from the current 2024 map will *not* restore missing text.
- `human_study/backend/human_study/questions.py`: intervention LLM generation uses `item.original_wording` and its choices; an unsuccessful generation/mapping attempt can fall back to that same incomplete source text.
- `data/raw/README.md` and `scripts/build_all_gss_native_maps.py`: authoritative survey PDFs are intentionally not committed; the map-builder expects `data/gss/codebooks/GSS_2024_Codebook.pdf`.

## Adaptive item audit

The source `codebook_page` numbers below are **metadata reported by the repository map**, not pages of a PDF independently inspected during this audit.

| Item(s) | GSS 2024 map codebook page(s) | Finding |
|---|---|---|
| `nataid`, `natchld`, `natcity`, `natcrime`, `natcrimy`, `natdrug`, `nateduc` | 126, 128, 123, 124, 132, 124, 125 | Topic plus abbreviated spending-question stem in parentheses; not a verbatim, standalone question |
| `natenrgy`, `natenviy`, `natheal`, `natrace`, `natroad`, `natsci`, `natspac` | 129, 130, 123, 125, 127, 129, 122 | Topic or abbreviated spending-question stem; `natenviy` is a topic label alone |
| `eqwlth`, `helppoor`, `helpsick`, `helpnot` | 136, 204, 205, 204 | Source text ends abruptly at 254–255 characters |
| `fejobaff`, `fefam` | 215, 201 | Source text ends abruptly at 254–255 characters |
| `fehire` | 217 | Incomplete/malformed introductory response-scale sentence before the substantive statement |
| `letin1a` | 229 | Open-ended stem ending “should be”; the choices may complete it, but original questionnaire context should be checked |
| `workhard`, `helpoth` | not supplied | Only short phrases present in 2024 map; missing ranking-question stem/context. Longer text in 2021/2022 is **not** verified for 2024 |
| `getahead`, `goodlife`, `happy`, `health` | 176, 226, 153, 154 | Appears self-contained in the checked 2024 semantic map |

**Summary:** 24/28 adaptive items need full-text verification before representing them as complete original GSS questions; 4/28 appear self-contained. This is a conservative editorial/source-quality audit, not a claim that the underlying GSS questionnaire is deficient.

## Other phases

- Baseline `confinan` ends in “financial inst” in the 2024 map and needs the complete institution name (2024 codebook page available in the row).
- The other baseline items and all three outcome items have not been independently checked against the original 2024 questionnaire. The 2024 source map should not be mistaken for a verbatim instrument merely because individual text fields look complete.

## Missing authoritative source

To finish the exact-wording repair, obtain **the official GSS 2024 questionnaire/instrument**, including the respondent-facing text, introductions/stems, and answer scales, or the complete official `GSS_2024_Codebook.pdf` **if** its labels actually contain the untruncated original questions.

The canonical local codebook path already expected by DTAG is `data/gss/codebooks/GSS_2024_Codebook.pdf`. Its contents are absent from tracked repository data. Raw source documents should remain outside Git unless redistribution is permitted.

For each corrected item, the next change must:
1. Verify the complete *2024* question against authoritative source, with page/section provenance.
2. Update `human_study/config/study.example.yaml` or a verified source-of-truth override used by its builder, preserving the same `item_id` and native `native_value` categories.
3. Preserve evidence that the item wording covers the intended response categories; ensure scale labels are understandable without inventing category values.
4. Test LLM question generation and reverse-mapping using the actual revised text, and ensure a fallback never presents truncated metadata to participants.
5. Keep `reviewed: false` until investigator/instrument approval; test with synthetic traffic only beforehand.

**Do not fabricate a GSS 2024 full question by expanding a 255-character fragment, combining snippets across items, or silently using an earlier-wave version.**
