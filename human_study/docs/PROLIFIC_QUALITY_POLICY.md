# Prolific participant-quality and rejection-eligibility protocol

**Status:** Draft for investigator/ethics review and pilot validation; not a Prolific
approval, automated payment rule, or justification for rejecting any person.
**Instrument:** GSS 2024 native DTAG V3, approximately 20–25 minutes
(6 baseline + 20 adaptive + 5 interleaved attention checks).
**Policy version:** \`prolific-rejection-eligibility-v1\`.

## Prolific's requirements

According to Prolific's [Attention and Comprehension Check Policy](https://researcher-help.prolific.com/en/articles/445153-prolific-s-attention-and-comprehension-check-policy),
studies of at least **five minutes** require **two or more failed valid attention
checks** for rejection on this basis. Valid instructional manipulation checks
(IMCs) must clearly and visibly instruct the participant how to respond to
**that question**, without requiring prior knowledge, memory recall, or fast
responses. Invalid factual-knowledge checks must not count.

Prolific's [Who should I reject?](https://researcher-help.prolific.com/en/articles/445218-who-should-i-reject)
also recognizes **objectively demonstrated low effort throughout a study**
when the expected engagement is explicit; it does not permit rejecting people
solely for failing an arbitrary internal measure, holding disagreeable beliefs,
answering one question quickly, or because of a researcher technical error.

Rejection on Prolific **withholds payment and can harm participant standing**.
[Excluding research data](https://researcher-help.prolific.com/en/articles/703724-what-to-do-with-flagged-responses)
is a separate scientific decision that generally does not negate compensation.
[Consent withdrawal](https://researcher-help.prolific.com/en/articles/445219-how-do-i-reject-or-return-a-submission)
is a reason to request return (and delete data as applicable), not reject.

## Five standard, non-adaptive, compliant IMCs

All five are \`kind: instructed_token\` with \`render: verbatim\`. They are
presented **within the current question** in the normal-sized response UI. No
LLM reformulation, memory, historical knowledge, or speed requirement is used.

| After substantive answer | Expected word | Exact pattern |
| --- | --- | --- |
| 3 | cobalt | Explicitly include the word **cobalt** in this answer |
| 8 | violet | Explicitly include the word **violet** in this answer |
| 13 | amber | Explicitly include the word **amber** in this answer |
| 18 | marble | Explicitly include the word **marble** in this answer |
| 24 | cedar | Explicitly include the word **cedar** in this answer |

Each actual prompt reads:

> Attention check: To show that you have read this question, include the exact
> word **[token]** in your answer. You may write that word on its own.

Answers match the specified word as a **case-insensitive whole word**, even
inside a longer answer. No question is graded on political or factual content.
The IMC outcome never conditions the LSM. These checks are intended for a
pilot: inspect how the checks display on mobile/desktop and monitor unexpected
failures before considering researcher-initiated rejections. Prolific may
request screenshots or evidence of valid wording.

## Stricter DTAG eligibility rule

The study deliberately uses a more conservative threshold than Prolific's
two-failure minimum. In \`rejection_eligibility.py\`:

| Objective evidence | \`eligible_for_rejection\` | Rationale |
| --- | --- | --- |
| 0–1 failed valid IMCs | **false** | Insufficient under the study rule |
| 2 failed valid IMCs only | **false** | Additional independently verified low effort required |
| 2 failed valid IMCs + quality score 60–100 | **false** | Internal score is not a Prolific rejection criterion |
| 2 failed valid IMCs + repeated obvious keyboard-mash filler on ≥60% of substantive questions, at least 5 repeats and at least 8 questions | **true** | Narrow objective demonstration of nonresponse throughout |
| ≥3 failed valid IMCs | **true** | Meets the stricter preregistered attention rule |

The repeated-filler rule accepts only **exact, unambiguous keyboard-mash
strings** from a small, versioned allowlist (e.g., \`asdf\`, \`asdfghjkl\`,
\`qwerty\`), never ordinary responses such as “yes”, “no”, “I don't know”, or
consistent ideological views. This deliberately misses some real low-effort
cases to avoid false accusations. An LLM confidence score, speed, word count,
generic duplicates, or an arbitrary combination of quality scores are **not**
independent objective evidence.

**A true eligibility flag is not a rejection.** The application does not
submit rejection requests or withhold payments. A researcher must verify the
exact displayed checks, original responses and context, item accessibility,
consent, applicable Prolific rules and any explanations. If the evidence is
uncertain, approve/pay the completed submission. Rejection, when justified,
must be initiated explicitly through Prolific by an authorized researcher.

A two-check case with high but nonconclusive quality-risk indicators has
\`two_failures_need_independent_evidence=true\` and
\`eligible_for_rejection=false\`. It can be examined or scientifically
excluded according to a separately prespecified plan; it must not be rejected
on this flag alone.

## Versioned archival and research export

After a participant reaches the completion boundary:

- \`reward.json\` and \`final.json\` record
  \`rejection_eligibility.eligible_for_rejection\`, \`basis\`,
  \`valid_imc_failures\`, \`failed_check_ids\`, limited objective
  \`low_effort_evidence\` with question IDs, the decision rule version,
  \`review_required_before_prolific_rejection=true\`, and
  \`prolific_rejection_executed=false\`.
- Verbatim displayed questions, attention-check answers and substantive answers
  remain in the private \`final.json\` archive for restricted investigator
  examination; they are not exposed to the participant-side public API.
- Investigator-only \`participants.csv\` exports
  \`eligible_for_rejection\`, \`rejection_eligibility_basis\`,
  \`two_failures_need_independent_evidence\`, and the independent
  \`quality_review_score\`.
- If \`eligible_for_rejection\` is true, the configured \`review_code\` is
  issued. Register this as a Prolific **Failed attention checks** completion
  path, ensuring submissions are available for **manual review** rather than
  automatically rejected. The standard \`completion_code\` is issued
  otherwise. A separate \`no_consent_code\` requests a return. No code is
  unique to a participant.

**Important:** The software's \`reward\` string only describes the advertised
study reward. Prolific administers and governs payment; no internal flag can
partially reduce it. Align any recruitment study's Prolific completion paths
and codes before invitations are sent.

## Verification and release criteria

Run:

\`\`\`bash
bash human_study/scripts/check_v3.sh
\`\`\`

The Prolific portion and eligibility unit tests are also part of the
\`human-study-native-parity\` GitHub Actions workflow. Check the CI result
**for the final commit**, run an end-to-end Cloud Run session with all five IMCs,
confirm GCS \`final.json\` fields, and test the three Prolific completion paths
before paid recruitment. Freeze the policy and instrument version before
enrollment, or use a fresh study ID for later amendments.

A passing offline test does not constitute Prolific approval or an investigator
determination that any particular participant should be rejected.
