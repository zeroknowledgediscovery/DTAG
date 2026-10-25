# GSS 2024 source-wording audit — human-study instrument

Date: 2026-10-24. Branch: `experiment/prolific-human-study`.

**Status: BLOCKED for a verified, complete-question instrument.** This is a source inventory and missing-data report, **not** a substitute for full questionnaire text. No wording has been reconstructed or inferred.

## Implementation update: LLM completion is now permitted (2026-10-24)

The study now **keeps the original incomplete text unchanged** in the draft instrument. Its new
`source_text_incomplete: true` flag marks the 24 affected adaptive items and the truncated
`confinan` baseline item. `human_study.instrument` generates the same flag whenever the
draft instrument is regenerated. The LLM is explicitly instructed to make a complete, neutral,
standalone question using only available text and native response labels; it must not invent
substantive details not supported by that context. Reverse semantic mapping must identify
the intended survey variable exactly. The unmodified source, generated question and provenance
are retained in the immutable study archive.

**Generated completion is not verified original GSS wording.** Any scientifically relevant
missing anchors, numeric response labels and semantic ambiguities still require review. The
application is not yet approved for actual participant recruitment; the draft stays
`reviewed: false`. A known incomplete source is never shown as fallback when the model or
semantic validation fails: the question remains pending and can be retried.

The "blocked" status in the original audit below refers specifically to reconstructing
**verified verbatim GSS 2024** original text, not to generating experimental questions with
a clearly labeled LLM completion.

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

## Verified 2024 NATENVIY correction (internal pilot)

The official NORC **GSS 2024 Ballot 3 English** questionnaire, PDF page 45
(zero-indexed page 44), explicitly asks whether respondents think the country
is spending too much, too little, or about the right amount on **the environment**
for `NATENVIY`. This is the **alternate wording form**, distinct from
`NATENVIR`, which asks about *improving and protecting the environment*.
Source: https://gss.norc.org/content/dam/gss/get-documentation/pdf/quex/GSS2024_Ballot3_English.pdf

Our original instrument map supplies `NATENVIY` only as “Improving and protecting
the environment,” without the required spending stem. This is **not** the
form-specific respondent-facing wording. As an interim fail-closed pilot
measure, `human_study.questions` supplies the verified 2024 reference for
LLM rewriting *only* when the source fragment and native choices match the
known defective entry. Form-specific checks verify the spending scale and
disallow `NATENVIR` wording. The cross-variable reverse mapper is not used
for this form, because it cannot reliably disambiguate near-duplicate
experimental forms. The generated-question record distinguishes
`validation_method=verified_2024_form_specific_reference_v1` from
`mapper_hit`, and retains the source citation.

**Before participant recruitment**, incorporate this verified source and
its form-specific provenance directly in the immutable reviewed instrument
and audit the other truncated items against the 2024 ballots. In particular,
`workhard` and `helpoth` are forced ranking tasks and cannot be faithfully
administered as independent importance-rating questions. This pilot fix
does not validate those items or all other incomplete stems.

## Completed-pilot question inspection (2026-10-24)

A complete 36-question session confirms end-to-end operational flow, **not**
respondent-facing wording fidelity. A preliminary static source review found:

- **Nine baseline institution items** (`conbus`, `coneduc`, `conpress`,
  `conmedic`, `contv`, `conjudge`, `consci`, `conlegis`, `conarmy`)
  are **not** flagged `source_text_incomplete`, although their map-sourced text
  embeds the common institutional-confidence question in parentheses and
  appends the institution name after the question mark. The production code
  passes them through unchanged as `canonical-common-instrument`.
  The 2024 Ballot 3 questionnaire indeed encodes the institution as a separate
  name under the shared question; this formatting must be converted to one
  standalone question in a respondent-facing web survey.
- `workhard` and `helpoth` use **relative child-value ranking** options.
  A generated isolated importance question is not equivalent to the source
  forced-ranking task.
- `eqwlth`, `helppoor`, `helpsick`, `helpnot` include plain numeric
  `display_label` values that are not self-describing.
- Other flagged excerpts may be presented only when LLM-generation validation
  succeeds. A successful reverse lexical/LLM match is not proof of response-
  scale fidelity, original wording, or questionnaire-form identity.

To inspect **the exact questions displayed in a completed session** (without
printing participant answers, identifiers, treatment arm or outcome indices):

```bash
gcloud storage ls --recursive gs://pkcsaas-01-dtag-study-data/studies/pilot-001/sessions/ | grep '/final.json
To finish the exact-wording repair, obtain **the official GSS 2024 questionnaire/instrument**, including the respondent-facing text, introductions/stems, and answer scales, or the complete official `GSS_2024_Codebook.pdf` **if** its labels actually contain the untruncated original questions.

The canonical local codebook path already expected by DTAG is `data/gss/codebooks/GSS_2024_Codebook.pdf`. Its contents are absent from tracked repository data. Raw source documents should remain outside Git unless redistribution is permitted.

For each corrected item, the next change must:
1. Verify the complete *2024* question against authoritative source, with page/section provenance.
2. Update `human_study/config/study.example.yaml` or a verified source-of-truth override used by its builder, preserving the same `item_id` and native `native_value` categories.
3. Preserve evidence that the item wording covers the intended response categories; ensure scale labels are understandable without inventing category values.
4. Test LLM question generation and reverse-mapping using the actual revised text, and ensure a fallback never presents truncated metadata to participants.
5. Keep `reviewed: false` until investigator/instrument approval; test with synthetic traffic only beforehand.

**Do not fabricate a GSS 2024 full question by expanding a 255-character fragment, combining snippets across items, or silently using an earlier-wave version.**

# Choose one exact object path returned above:
gcloud storage cat "$FINAL" | python3 human_study/scripts/audit_completed_questions.py - --show-original
```

The audit screens for raw fragments, numeric labels, ranking scales, provider
fallbacks and missing source verification. It reports all displayed wording and
choices for investigator examination. An issue-free *heuristic* report does
**not** imply validation against the source questionnaires.

**Do not overwrite historical final.json objects or silently alter the deployed
reviewed.yaml.** Correct the next instrument version and verify all its
questions/response scales before recruiting Prolific participants.

2024 official source: https://gss.norc.org/get-documentation/questionnaires.html
(2024 Cross-Section Ballot C / Ballot 3 English, institutional confidence
questions around questionnaire page 93).

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
