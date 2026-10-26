# Offline GSS wording catalog: source reconstruction outside participant latency

The experiment continues to use the original native DTAG optimizer and its full
eligible variable set. **This catalog never selects, scores, excludes, ranks,
or conditions a variable.** Once DTAG selects a variable, the renderer attempts
an exact source-backed wording lookup. A catalog miss runs the existing
source-grounded language generator. The participant's free-text answer is
still mapped into zero or more native GSS observations by the unchanged
`map_human_response`, `interpret_multi` and `resolve` pipeline.

## Real compilation coverage

The compiler starts with the **811** native GSS 2024 model features from the
official-model audit, *not* the 228 first-state candidates. It uses the
preexisting audited wording contracts, validated native answer alphabets, and
original-map content hashes. The build generates:

- `human_study/data/gss_2024_compiled_wording.json` — immutable runtime index
- `human_study/data/gss_2024_compiled_wording.coverage.json` — 811 individual
  statuses, validation failures, and fallback counts

Some source-contract entries may be withheld by stricter checking. This is
reported in the coverage file, rather than silently removing their variable
from the scientific model. The remaining variables still use the online LLM
reconstruction path. **A codebook label by itself is not a verified standalone
question.** This version does not label automatically generated LLM wording as
source-certified.

## Lookup correctness

Every entry is keyed by native variable ID, model release, canonical map label
hash, native answer-value hash, and displayed-label hash. The value and label
order are significant. The lookup also checks standalone completeness, the
source-specific wording contract (when present), and visible response choices.
Any changed/unknown form safely misses and uses the existing grounded LLM
fallback. Catalog successes carry `provider=compiled-source`,
`cache_hit=true`, `generation_attempts=0`, and a stable provenance hash.

This is deterministic question presentation, not a static *selection* bank.

## Reproduce the offline compilation

The GitHub Action `.github/workflows/audit-gss2024-full-native.yml` downloads
the original native model and the 2024 Release 2 NORC codebook, audits all
811 features, compiles certified source-contract wording, verifies live lookup
coverage against every native feature, and commits the versioned catalog.

To run manually after preparing a codebook-backed native audit:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/human_study/scripts:$PWD/scripts:$PWD"
python human_study/scripts/audit_all_native_gss_2024.py \
  --codebook /path/to/GSS_2024_Codebook_R2.pdf --out /tmp/dtag_all
python human_study/scripts/compile_gss2024_wording.py \
  /tmp/dtag_all.json \
  --out human_study/data/gss_2024_compiled_wording.json
```

## Expand coverage safely

Optional offline drafting **does not call an LLM at runtime and does not publish
unreviewed wording**. To create a bounded collection of drafts using your
locally configured `OPENAI_API_KEY`:

```bash
python human_study/scripts/compile_gss2024_wording.py \
  /tmp/dtag_all.json --generate-drafts --draft-limit 50 \
  --drafts-out /tmp/gss_question_drafts.json
```

The draft file identifies source map text, original supported answer labels,
context provenance, missing-information reports and deterministic validation
results. A researcher must verify original wording, conditional routing,
scale semantics, and exact native answer correspondence before explicitly
approving it in a separate review file.

To approve a reviewed item, create a JSON object keyed by its variable name,
with `question`, `reviewer`, `source_reference`,
`source_map_sha256`, and `native_answers_sha256` populated with the exact
fingerprints supplied by the draft report. Then run:

```bash
python human_study/scripts/compile_gss2024_wording.py \
  /tmp/dtag_all.json --reviewed-json /path/to/reviewed.json \
  --out human_study/data/gss_2024_compiled_wording.json
```

The reviewed question is still checked for source constraints, complete
response alternatives, and orphaned referents. Changed semantic-map text or
native model answer labels invalidates the review. Researcher approval is a
positive act; LLM output alone is **never** silently auto-certified.

## Expected latency and scientific boundaries

A catalog hit removes the *next-question generation* OpenAI request, normally
one and potentially two requests after a validation retry. The independent
written-answer variable mapping and multi-variable answer interpretation
remain unchanged and may still dominate the total response-to-next-question
delay. No numerical savings can be promised without live timing data.

This is designed to standardize exposure to the same verified wording across
sessions, prevent repeat paraphrase drift and remove unnecessary online model
calls. It does **not** certify all 811 model features, repair conditional
source items automatically, or change recorded scientific results.

`bash human_study/scripts/check_v3.sh` exercises the catalog and unchanged
multi-variable mapping, but full-length live participant tests are still
needed before recruiting paid participants. No deployment is automatic.
