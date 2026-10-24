# DTAG session report — Respondent run06

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:23:57+00:00  ·  session `2c6d5307d3474f13b443a47540e84b2a`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:23:05+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206050, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 4 variables (0 forced by geography/time); dropped LLM assignments: 2. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0858 → current -0.0727 (change +0.0131)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q4 -0.0475; Q7 +0.0291; Q10 +0.0276; Q3 -0.0260; Q2 +0.0173

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=yes, fired | changed | +0.0016 | -0.0842 |
| 2 | Should a person who wants to say that Black people are genetically inferior be allowed to make a speech in your community, or should they not be allowed to speak? | DIRECT | `spkracy`=yes, allowed to speak; `spkrac`=not allowed | changed | +0.0173 | -0.0669 |
| 3 | If a Muslim clergyman wanted to give a speech in your community expressing hatred of the United States, should he be allowed to speak or not? | DIRECT | `spkmslm`=not allowed; `spkmslmy`=yes, allowed to speak; `libmslm`=not remove; `libmslmy`=remove | changed | -0.0260 | -0.0929 |
| 4 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=not religious at all | changed | -0.0475 | -0.1404 |
| 5 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=agree; `immjobs`=disagree strongly; `immwlfare`=agree | changed | -0.0102 | -0.1506 |
| 6 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate the Republican Party? | DIRECT | `raterepp`=50.0 | changed | +0.0088 | -0.1418 |
| 7 | Which of the following best describes what you believe about God? | DIRECT | `god`=believe sometimes; `biblev`=other (phone mode only: volunteered); `bible`=inspired word; `biblenv`=word of god | changed | +0.0291 | -0.1128 |
| 8 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=strongly favor | changed | +0.0091 | -0.1037 |
| 9 | How important is it to you to obey? | DIRECT | `obey`=2nd important; `obeylaws`=6.0; `amgovt`=very important; `paytaxes`=very important | changed | +0.0033 | -0.1003 |
| 10 | Do you think sexual relations between two adults of the same sex are always wrong, almost always wrong, wrong only sometimes, or not wrong at all? | DIRECT | `homosex`=almost always wrong | changed | +0.0276 | -0.0727 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
