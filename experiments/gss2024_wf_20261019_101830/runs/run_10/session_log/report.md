# DTAG session report — Respondent run10

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:27:22+00:00  ·  session `0a0bd2773e7047a59f9bf4d36d4c7319`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:26:29+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206054, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 6 variables (0 forced by geography/time); dropped LLM assignments: 2. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0860 → current +0.0950 (change +0.1809)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q1 +0.0740; Q3 +0.0453; Q2 +0.0173; Q5 +0.0172; Q4 +0.0135

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=not allowed; `colcomy`=yes, fired | changed | +0.0740 | -0.0119 |
| 2 | Should a person who wants to say that Black people are genetically inferior be allowed to make a speech in your community, or should they not be allowed to speak? | DIRECT | `spkracy`=yes, allowed to speak; `spkrac`=not allowed | changed | +0.0173 | +0.0053 |
| 3 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=moderately religious | changed | +0.0453 | +0.0506 |
| 4 | How important is it to you to be a Christian? | DIRECT | `amchrstn`=very important | changed | +0.0135 | +0.0642 |
| 5 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=agree; `immjobs`=agree; `immwlfare`=disagree strongly | changed | +0.0172 | +0.0814 |
| 6 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=favor | changed | +0.0016 | +0.0830 |
| 7 | Do you agree or disagree that the United States would be a better country if religion had less influence? | DIRECT | `religinf`=neither agree nor disagree | changed | +0.0021 | +0.0851 |
| 8 | How do you feel about a close relative marrying an Asian American person? | DIRECT | `marasian`=strongly favor | changed | -0.0007 | +0.0843 |
| 9 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate Donald Trump? | DIRECT | `ratechall124`=45.0 | changed | +0.0096 | +0.0939 |
| 10 | Were you attempting to escape from custody? | DIRECT | `polescap`=no | changed | +0.0011 | +0.0950 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
