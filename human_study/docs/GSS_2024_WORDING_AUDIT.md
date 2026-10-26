# GSS 2024 standalone-question wording audit

**Status:** Source-grounded remediation of known risks; not a certification that
every item from the full 2024 semantic map is an appropriate independent
question. Applies to DTAG's *human_study* native-webapp participant interface,
not to the native LSM, its variable coding, or the original DTAG optimizer.

## Trigger: observed colmslm failure

A completed 31-screen synthetic browser session contained the following
participant-facing question:

> Do you think this person should be allowed to teach in a college or university?

Variable: `colmslm`. The 2024 NORC GSS release-2 codebook, p.119, describes
its respondent as **a Muslim clergyman who preaches hatred of the United
States**. COLMSLM appears after the corresponding SPKMSLM item in the original
survey; the semantic-map field for COLMSLM contains only “Should such a person
be allowed to teach ...?”. DTAG selects questions independently, so context
must accompany the item. The missing subject is a confirmed substantive
measurement defect, not merely a cosmetic issue.

**Authoritative source:**
[NORC GSS 2024 Codebook Release 2, p.119](https://gss.norc.org/content/dam/gss/get-documentation/pdf/codebook/GSS%202024%20Codebook%20R2.pdf#page=192).

## Corrected question-generation behavior

- `wording_contracts.py` supplies investigator-anchored complete input
  contexts for known context-dependent GSS variables.
- For `colmslm`, the new input explicitly identifies the Muslim clergyman,
  hatred of the United States, and college teaching.
- `QuestionLLM.generate` verifies the required referent, topic and action
  in the generated participant-facing question. Incorrect or underspecified
  outputs are rejected, and generation is retried. If all attempts fail, an
  explicit `QuestionGenerationError` prevents the defective question from
  being shown; it does not substitute a silently shortened version.
- A generic fail-closed check also rejects leading orphan subjects (“Do you
  think this person ...?”, “Should such a person ...?”), copied codebook
  ellipses, unresolved data-template placeholders, and similar obvious
  fragments.
- The **original** GSS map label, variable ID, answer coding and native
  optimizer remain unchanged in scientific provenance. The improved context
  is used for question construction and source validation only.
- These changes intentionally make wording a *hard release gate* for
  covered items. The same selection may occasionally need repeated question
  generation or produce an error; the application must not show an
  unvalidated question just to maintain progress.

## Other confirmed source-context risks

Inspecting the canonical `maps/gss/gss_2024_map.csv` against NORC's 2024
release-2 codebook identified the following families:

| Family | Defect risk | Mitigation |
| --- | --- | --- |
| Civil liberties (`col*`, `lib*`, `spk*`) | Follow-on prompts refer to an unidentified person or book | Standalone scenarios for atheist, racist-belief, communist, Muslim-clergyman, and selected experimental wording variants; preserve distinct teaching-versus-firing question |
| Abortion (`ab*`, `ab*g`) | “If she ...?” strips the common *legal abortion* stem | Complete legal-abortion question and item-specific condition |
| Suicide (`suicide1/2/4`, grid forms) | Scenario fragment omits question about the right to end one's life | Restored common stem and circumstance |
| Government spending (`nat*`) | Map holds issue name under an abbreviated spending stem | Complete spending question with too-much/too-little/about-right response framing; distinct variants retained |
| Income differences (`eqwlth`) | Canonical label ends mid-sentence | Complete both ends of government-redistribution scale |
| Institutional confidence (`con*`) | Stem about the *people running* each institution is only contextual | Restore named institution and confidence scale |
| Police-force vignettes (`polabuse*`, `polmurdr`) | Conditional fragments omit whether police may strike a person | Restore action and specific vignette |
| Racial inequality (`racdif1-5`) | Grid fragments omit comparative reference group or causal attribution | Restore comparisons and the specified causal explanation |
| Gender-role attitudes (`fechld`, `fepresch`, `fefam`) | Shared agree/disagree stems and a truncated FEFAM label | Restore explicit statement and four-level agreement scale |
| Racial-inequality wording experiment (`racdif1x-5x`) | Codebook/map labels terminate in an unfinished cause | **Excluded by ID** from current full Prolific draft/test configurations pending the actual questionnaire wording |

The `racdif*x` exclusion is an explicit scientific instrument change:
questions from those five variables cannot be selected as DTAG adaptive
candidates under the current study configs. There is **no alteration** to
the shared optimizer or native LSM state geometry. If these variables are
eventually restored, verify their experimental form independently and
release under a new study ID/config hash.

Some other GSS map rows have interviewer skip instructions, grid context,
conditional demographics or form-specific fillers. A source excerpt can be
problematic even when the LLM generates grammatically correct prose; the
deterministic contracts above reduce but cannot remove all such risks.

## Reproducible full-map inspection

Run from the repository root with the standard V3 Python environment:

```bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/scripts:$PWD"
python3 human_study/scripts/audit_gss_wording_map.py --check \
  --out /tmp/dtag-gss-2024-wording-audit.json
```

This reads **all rows in the canonical GSS 2024 semantic map**, identifies
labels with known context/truncation cues, checks registered wording
contracts against their own mandatory patterns and verifies that the five
unverifiable `racdif*x` items remain excluded. The report enumerates
residual flagged rows for subsequent investigator classification.

The first offline scan of the 2024 canonical map found **813 entries**,
**99 potentially context-dependent** source labels, **102 validated source
contracts**, and **13 flagged labels without a contract**. The residual
variable IDs were `sphrs1`, `granborn`, `socrel`, `socommun`,
`socfrend`, `socbar`, `rank`, `dofirst`, `sexsex`, `uscitzn`,
`spanself`, `whatslf2`, and `devtype`.

Do **not** interpret the residual flag count as the number of defective
*askable* questions: the raw map contains metadata, demographics, and other
variables outside DTAG's dynamically selected opinion set. To cross-check
the *actual empty-state native opinion candidate pool*, run:

```bash
python3 human_study/scripts/audit_gss_wording_map.py --native-candidates --check
```

This optional command requires the installed GSS native model and may download
its model artifacts. The check must pass before paid enrollment. It does not
certify all state-dependent candidate universes across 20 adaptive questions.
A complete instrument qualification additionally needs an audit across
multiple actual native states and representative live OpenAI-generated
questions.

## Validation and deployment

Regression tests in `test_v3_question_referents.py` verify the repaired
COLMSLM prompt, reject missing-referent LLM outputs, and check other source
families. CI runs these tests plus the map scanner, alongside existing V3
native parity and Prolific integration tests.

The revised GCP test instrument is versioned separately as
`prolific-v3-gcp-wording-audit-v1`. Earlier browser sessions, including
the observed `colmslm` question, are **not** retroactively corrected.
Redeploy the revised instrument, confirm the deployed code SHA, and run a
fresh full-length browser session before Prolific recruitment.
