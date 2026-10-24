# DTAG session report — Respondent run11

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:28:12+00:00  ·  session `9cc3e0770d4c4cd29b8c63063fed1644`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:27:25+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206055, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 7 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0911 → current +0.0204 (change +0.1114)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q2 +0.0455; Q1 -0.0236; Q10 +0.0217; Q4 +0.0180; Q5 +0.0143

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colmslm`=yes, allowed to teach | changed | -0.0236 | -0.1147 |
| 2 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=moderately religious | changed | +0.0455 | -0.0692 |
| 3 | How important is it to you to be a Christian? | DIRECT | `amchrstn`=very important | changed | +0.0135 | -0.0557 |
| 4 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=agree; `immjobs`=agree; `immwlfare`=disagree strongly | changed | +0.0180 | -0.0377 |
| 5 | Do you think a person who believes that Black people are genetically inferior should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=yes, allowed to teach | changed | +0.0143 | -0.0234 |
| 6 | Do you agree or disagree that the United States would be a better country if religion had less influence? | DIRECT | `religinf`=neither agree nor disagree | changed | +0.0020 | -0.0214 |
| 7 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=strongly favor | changed | +0.0089 | -0.0124 |
| 8 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate Donald Trump? | DIRECT | `ratechall124`=45.0 | changed | +0.0096 | -0.0028 |
| 9 | Were you attempting to escape from custody? | DIRECT | `polescap`=no | changed | +0.0015 | -0.0014 |
| 10 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate the Republican Party? | DIRECT | `raterepp`=70.0 | changed | +0.0217 | +0.0204 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
