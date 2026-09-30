# Optimized CM / WF ideology question sets (GSS 2024)

Question sequences chosen to move the ideology index of the conservative-male (CM) and
progressive-female (WF) personas in a chosen pair of directions. Each file is
`step,question` and can be uploaded as-is with **Run sequence…** in the web app
(two-respondent mode runs it on both at once) or used with the CLI autoplay.

| File | Goal | Questions | CM (start → end) | WF (start → end) |
|---|---|---:|---|---|
| `gss2024_same_both_up.csv` | same direction: both right, at every step | 12 | +0.009 → +0.230 (**+0.222**) | −0.096 → +0.132 (**+0.227**) |
| `gss2024_same_both_down.csv` | same direction: both left, at every step | 12 | +0.009 → −0.408 (**−0.417**) | −0.096 → −0.470 (**−0.374**) |
| `gss2024_opposite_cm_up_wf_down.csv` | opposite: CM right, WF left (net over the set) | 12 | +0.009 → +0.230 (**+0.222**) | −0.096 → −0.321 (**−0.225**) |
| `gss2024_opposite_cm_up_wf_down_strict.csv` | opposite: CM right, WF left at every step | 4 | +0.009 → +0.118 (**+0.110**) | −0.096 → −0.333 (**−0.237**) |
| `gss2024_opposite_wf_up_cm_down.csv` | opposite: WF right, CM left (net over the set) | 12 | +0.009 → −0.007 (**−0.015**) | −0.096 → −0.081 (**+0.015**) |

"Opposite directions" is realised by the last three files; `gss2024_trajectories.csv` has
every step: survey variable, question, each persona's answer, the index change and the
running index.

## How they were found

- Model: native GSS 2024 LSM, wave-specific poles (`assets/polar_vectors/gss/gss_2024_polar_vectors.csv`, v2 right pole).
- Answering exactly as the DTAG runtime does with **state updates on** and **`resp_mode max`**:
  each question's survey variable takes its most likely answer given the respondent's
  current state, the answer is written into the state, and the index is recomputed, so
  every answer conditions the next.
- Persona states, hand-coded from the configured persona texts (only stated facts):
  - CM (`gss2024_cm`): male, 45, white, South, 2 children, open country, reads news every day,
    working full time, veteran (2–4 years), polviews = conservative.
  - WF (`gss2024_wf`): female, 22, white, Northeast, no children, large central city,
    reads news every day, working full time, no active duty, polviews = extremely liberal.
- Candidates: the 223 opinion items of GSS 2024. Excluded: respondent facts and identity
  (demographics, religious affiliation, past votes, household and gun ownership), party and
  left–right self-placement (they would relabel the persona rather than probe an opinion),
  behaviour logs, interviewer vignettes, survey meta-data, and split-ballot duplicates of an
  item.
- Search: greedy over the sequence, scoring each candidate by the worse of the two personas'
  signed moves; a step is added only if it improves that score by at least 0.001, up to 12
  questions. The "net" sets require the direction only for the whole set; WF-up/CM-down was
  found by searching combinations of single-question effects and then replaying the
  sequence in the model (the numbers above are the replayed ones).
- Questions are written in plain English from the GSS wording of each variable so that
  DTAG's variable selection maps each one to its intended item.

## What the results show

- The model answers most items identically for both personas, so most questions move both
  indices by about the same amount. Moving both together is easy (±0.2–0.4).
- The personas separate on religiosity (prayer, religion's influence, the Bible, being a
  Christian as American), defence spending, reparations and aid to Black Americans; on
  these CM answers conservatively and WF liberally, which is what makes CM-right/WF-left
  possible (prayer frequency alone: CM +0.095, WF −0.193).
- **WF right / CM left is barely achievable (±0.015).** No opinion item gives WF the more
  conservative answer. The set works only because identical answers move the two indices by
  slightly different amounts; treat it as a limit case, not a strong effect.

## Caveats

- Numbers assume one survey variable per question. With a real LLM, DTAG may select extra
  related variables (e.g. both Biden ratings), which changes the moves; check each run's
  *Model evidence*.
- Persona states in the app come from the LLM's reading of the persona text and may include
  more or different variables than the hand-coded states above.
- Order matters: answers carry forward, so a question reordered or asked on its own can move
  the index differently.
- Specific to GSS 2024 and the v2 poles; other waves need re-optimising.
