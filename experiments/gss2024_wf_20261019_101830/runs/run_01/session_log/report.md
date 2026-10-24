# DTAG session report — Respondent run01

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:19:22+00:00  ·  session `b14e3c289d2a48dbb5b4f467ed2059a9`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:18:33+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206045, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 7 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0845 → current -0.0131 (change +0.0713)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q3 +0.0453; Q1 +0.0251; Q2 -0.0138; Q4 +0.0124; Q7 +0.0088

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=not fired | changed | +0.0251 | -0.0593 |
| 2 | Should a person who wants to say that Black people are genetically inferior be allowed to make a speech in your community, or should they not be allowed to speak? | DIRECT | `spkracy`=not allowed; `spkrac`=yes, allowed to speak | changed | -0.0138 | -0.0732 |
| 3 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=moderately religious | changed | +0.0453 | -0.0279 |
| 4 | How important is it to you to be a Christian? | DIRECT | `amchrstn`=fairly important | changed | +0.0124 | -0.0155 |
| 5 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=agree; `immjobs`=disagree; `immwlfare`=agree | changed | -0.0014 | -0.0168 |
| 6 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate Donald Trump? | DIRECT | `ratechall124`=50.0 | changed | -0.0020 | -0.0188 |
| 7 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=strongly favor | changed | +0.0088 | -0.0100 |
| 8 | Do you agree or disagree that the United States would be a better country if religion had less influence? | DIRECT | `religinf`=neither agree nor disagree | changed | +0.0020 | -0.0080 |
| 9 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0066 | -0.0146 |
| 10 | Were you attempting to escape from custody? | DIRECT | `polescap`=no | changed | +0.0015 | -0.0131 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
