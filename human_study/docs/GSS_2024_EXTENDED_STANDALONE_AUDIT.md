# DTAG human study — expanded 2024 GSS standalone-question audit

**Historical snapshot:** The counts below describe the earlier static scan,
before the 21 confirmed source wording repairs. They must not be interpreted
as current unresolved defects. For the real 811-variable inventory, updated
contracts, remaining source-review work and current status, see
[GSS_2024_FULL_NATIVE_AUDIT_STATUS.md](GSS_2024_FULL_NATIVE_AUDIT_STATUS.md).


**Date:** 2026-10-26  
**Branch:** experiment/prolific-human-study  
**Scope:** Read-only audit of canonical \`maps/gss/gss_2024_map.csv\`,
existing \`wording_contracts.py\`, and the exact *static* opinion predicate
\`optimize_question_sets.askable()\`. Native indexability, possible-answer
support, and pole exclusions must be established separately with the
model-backed audit; this report does not assert actual selection for
every flagged item.

## Conclusion

**Not yet wording-qualified for paid human recruitment.** The original
ellipsis-focused scan missed substantial incomplete labels, shared-battery
instructions and omitted response scales, including the reported ACPTTG
failure (now independently repaired). A broad screening pass is necessary.

The static scan of the current repository reports:

| Screening metric | Count |
| --- | ---: |
| GSS 2024 map variables inspected | 813 |
| Pass approximate static webapp opinion predicate | 251 |
| In that static pool, existing source contract or special verified form anchor | 92 |
| In that static pool, without an existing contract/anchor | **159** |
| Of uncontracted static candidates: verified incomplete source | **21** |
| Of uncontracted static candidates: possible non-opinion/eligibility check | **20** |
| Of uncontracted static candidates: other source-completeness warning | **89** |
| Of uncontracted static candidates: no detector alert but unreviewed | **29** |

**Important:** 159 is a *review queue*, not 159 confirmed mistakes.
The static 251 is **not the actual empty-state native model candidate
count**: no model/conditional categories are loaded on the CI runner,
and the suffix filter uses CSV variable names as a provisional feature set.
The previous count of only **12** unresolved labels applied to a much
narrower ellipsis/orphan-reference detector, not this wider audit.

## 1. Source-confirmed missing context — priority P0

The following **21** *static-filter-passing*, uncontracted labels
have incomplete source meaning, shared interviewer instructions or
missing response anchors confirmed by their GSS 2024 R2 codebook entries:

| Family | Variables | Specific source problem |
| --- | --- | --- |
| Ranking child attributes | \`obey\`, \`popular\`, \`thnkself\`, \`workhard\`, \`helpoth\` | Map has only phrases such as “to obey”. Original asks the relative **first-through-fifth rank of five child qualities**, using the same list/card. Ranking cannot be recreated faithfully from the fragment alone |
| Police striking citizen | \`polescap\` | Map says “Was attempting to escape from custody?” but omits **whether police striking this citizen is approved** |
| Confidence in institutions | \`confinan\`, \`confed\` | Missing/truncated object of confidence, respectively the **financial institutions** and the **executive branch of the federal government**. The codebook has the three-point confidence response scale |
| Immigration levels | \`letin1\`, \`letin1a\` | One is a title (“number of immigrants increased or decreased”), the other stops at “should be”. The five increases/unchanged/decreases alternatives are essential |
| Pornography laws | \`pornlaw\` | “Which of these statements” is not independently answerable without the **three age-dependent distribution-law alternatives** |
| Family marriage attitude | \`marblk\`, \`marasian\`, \`marhisp\` | “What/how about having a close relative marry …?” loses the **favor/oppose** response task inherited from the grid |
| Feeling-thermometer/rating | \`rateincumb24\`, \`ratechall124\`, \`ratechall224\`, \`ratechall324\`, \`ratedemp\`, \`raterepp\`, \`ratemaga\` | “Rating of [name]” lacks the original numerical rating/thermometer format and meaning of its scale |

**Authoritative references:** NORC [GSS 2024 release-2 codebook](https://gss.norc.org/content/dam/gss/get-documentation/pdf/codebook/GSS%202024%20Codebook%20R2.pdf)
(pp. 142–153, 186, 206–211, 355, 428; consult each variable's
actual entry and native response codes), plus the
[2024 Ballot 1 questionnaire](https://gss.norc.org/content/dam/gss/get-documentation/pdf/quex/GSS2024_Ballot1_English.pdf).
Those ranges denote relevant sections, not exhaustive provenance for
every variable. Confirm all response categories and variant-specific
wording before constructing replacements.

All 21 **remain in the repository and candidate universe**. This audit
does not exclude or remap them.

## 2. Additional 89 source warnings — priority P1

The broader detector finds uncontracted *likely opinion* labels that
have a short fragment, missing interrogation, orphaned wording, or
unverifiable response task. Examples requiring individual codebook
comparison:

- Trust, efficacy, and democracy: \`satdemoc\`, \`poleff11\`, \`poleff18\`,
  \`trcourts\`, \`befair\`, \`cantrust\`, \`demtoday\`, \`dem10pst\`,
  \`dem10fut\`.
- National identity and civic duties: \`amchrstn\`, \`amgovt\`,
  \`amfeel\`, \`amancstr\`, \`amshamed\`, \`belikeus\`, \`ifwrong\`,
  \`paytaxes\`, \`obeylaws\`, \`watchgov\`, \`rghtsmin\`, \`oppsegov\`.
- Immigration and global issues: \`imports\`, \`immcrime\`,
  \`immameco\`, \`immjobs\`, \`immassim\`, \`amownway\`, \`wrldgovt\`,
  \`forland\`, \`amtv\`, \`immcrime1\`, \`immjobs1\`, \`immideas1\`.
- Media, trust, AI, and technology: \`smnews\`, \`tvnews1\`,
  \`papernews\`, \`radionews\`, \`webnews\`, \`trppl\`,
  \`trcong\`, \`emonitor1\`, \`gendtech\`, \`agetech\`,
  \`urbantech\`, \`eductech\`, \`classtech\`, \`aiworry\`.
- Government and social policy: \`incgap1\`, \`servpub\`, \`conscrp\`,
  \`dsndntpay\`, \`helppoor\`, \`helpnot\`, \`helpsick\`,
  \`helpblk\`, \`liveblks\`, \`meovrwrk\`, \`feovrwrk\`.

These are **warning signals**, not all confirmed wrong; a proposition
with a complete subject can sometimes be rewritten correctly with
native answer labels. However, the present generator validates
*grammar*, not original meaning or the category scale, for uncontracted
items. It cannot guarantee preservation of omitted content.

## 3. Separate eligibility review — priority P1

The static filter also passes **20** variables tagged for possible
non-opinion/conditional-task review. Examples include \`hrs1\`,
\`hrs2\`, \`spwrksta\`, \`reg16\`, \`rincom16\`, \`health\`,
\`jobfind\`, \`posslq\`, \`sexornt\`, \`sexbirth1\`, and \`spklang\`.
These might not be actual native candidates, but if eligible their
problem is not merely prose: these are factual/conditional or
respondent-specific tasks in an adaptive opinion study. This requires
**scientific eligibility review**, separate from source-wording
reconstruction. Do not silently drop them as a shortcut to passing a
wording test.

Another **29** uncontracted static candidates have no heuristic alert;
they still lack an item-specific semantic/answer-scale validator.

## 4. Why the existing 133 contracts and narrow audit did not catch this

- The original \`SUSPECT_SOURCE\` expression mainly looks for literal
  ellipses, templated references, and a few dependent constructions.
  It misses \`obey\`, \`letin1\`, \`rateincumb24\`, \`acpttg\`, etc.
- A contract's automated test checks that its **own source** matches
  its own required patterns. This does not establish that every
  uncontracted variable is complete or that all source-derived scales
  have been reviewed.
- Native-webapp \`QuestionLLM.generate()\` may accept any fluent LLM
  rewrite that passes generic \`validates_standalone()\` for
  uncontracted variables. The generic check cannot know the missing
  premise of a short source label.
- The client reports a grammatical standalone question even when the
  substantive measured construct has changed. This is exactly the
  previously observed \`ACPTTG\` failure.

## 5. Remediation sequence (not applied by this audit)

1. Compare all **21 P0** entries with the original 2024 ballot(s),
   codebook and *native* response options. Add item-specific
   validated complete wording contracts and failure-path tests;
   preserve variable identities and all native response codings.
2. Review the **89 P1** source warnings systematically against the
   same authoritative sources. Convert genuine context/scale deficits
   to contracts. Do not equate an abbreviated *label* with a
   defective *question* without checking the source.
3. Run the **20 P1 eligibility** cases through the exact model-backed
   candidate iterator; classify opinion versus respondent fact
   separately and obtain investigator signoff for any universe change.
4. Screen the remaining **29** uncontracted candidates by visual
   review, including their native category support.
5. Run randomized native-state candidate audits and scripted *live*
   LLM rewrites, automatically reject missing subject/scale,
   and repeat a full-length 31-question session after patches.
   A syntactic contract passing on one source string is not proof
   of universal question quality.

## Reproduce

No live GCP credentials are necessary for the static audit:

\`\`\`bash
export PYTHONPATH="$PWD/human_study/backend:$PWD/human_study/scripts:$PWD/scripts:$PWD"
python3 human_study/scripts/audit_standalone_candidates.py --compact
python3 human_study/scripts/audit_standalone_candidates.py --out /tmp/dtag-wording-all.json
python3 -m pytest -q human_study/tests/test_standalone_candidate_audit.py
\`\`\`

On a host with the native GSS model installed, audit the **actual**
empty-state native candidate set (this is a distinct, essential check):

\`\`\`bash
python3 human_study/scripts/audit_standalone_candidates.py \
  --native-candidates --out /tmp/dtag-wording-native.json
python3 human_study/scripts/audit_gss_wording_map.py --native-candidates --check
\`\`\`

\`--out\` includes every one of the 813 source excerpts, screening
flags, candidate classification, and codebook page. No participant
data are read or modified.

**Execution status:** Read-only source audit and regression checks pass
in CI. No study wording, model state, adaptive candidates, native
categories, LSM computations, or production configuration has been
changed in this audit pass. CI passing means the audit can reliably
*identify* the issues; it does **not** mean those issues are repaired.
