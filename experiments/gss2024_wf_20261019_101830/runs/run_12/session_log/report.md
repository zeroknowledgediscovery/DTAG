# DTAG session report — Respondent run12

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:29:02+00:00  ·  session `093fb544017f4b488c74b7ebed9a1724`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:28:14+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206056, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 8 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0845 → current +0.0856 (change +0.1700)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q3 +0.0500; Q4 +0.0453; Q1 +0.0251; Q2 +0.0173; Q9 +0.0148

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=yes, fired | changed | +0.0251 | -0.0593 |
| 2 | Should a person who wants to say that Black people are genetically inferior be allowed to make a speech in your community, or should they not be allowed to speak? | DIRECT | `spkracy`=yes, allowed to speak; `spkrac`=not allowed | changed | +0.0173 | -0.0421 |
| 3 | If a Muslim clergyman wanted to give a speech in your community expressing hatred of the United States, should he be allowed to speak or not? | DIRECT | `spkmslm`=not allowed; `spkmslmy`=not allowed; `libmslm`=remove; `libmslmy`=remove | changed | +0.0500 | +0.0079 |
| 4 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=moderately religious | changed | +0.0453 | +0.0532 |
| 5 | How important is it to you to be a Christian? | DIRECT | `amchrstn`=not very important | changed | +0.0061 | +0.0593 |
| 6 | If someone in your community said a book written by a person who believes that Black people are genetically inferior should be taken out of your public library, would you support removing it or not? | DIRECT | `librac`=remove; `libracy`=not remove | changed | +0.0095 | +0.0688 |
| 7 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=disagree; `immjobs`=disagree; `immwlfare`=agree | changed | -0.0048 | +0.0639 |
| 8 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=neither favor nor oppose | changed | +0.0003 | +0.0642 |
| 9 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=wrong only sometimes | changed | +0.0148 | +0.0790 |
| 10 | Do you agree or disagree that the United States would be a better country if religion had less influence? | DIRECT | `religinf`=disagree | changed | +0.0065 | +0.0856 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
