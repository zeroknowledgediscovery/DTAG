# DTAG session report — Respondent run17

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:33:26+00:00  ·  session `e6e9eac721ff48399516c57a8330fe6c`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:32:37+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206061, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 7 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0893 → current -0.0954 (change -0.0062)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q3 -0.0475; Q5 +0.0294; Q7 +0.0188; Q1 +0.0090; Q10 -0.0090

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=yes, allowed to teach; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=not fired | changed | +0.0090 | -0.0802 |
| 2 | If a Muslim clergyman wanted to give a speech in your community expressing hatred of the United States, should he be allowed to speak or not? | DIRECT | `spkmslm`=not allowed; `spkmslmy`=not allowed; `libmslm`=not remove; `libmslmy`=not remove | changed | -0.0051 | -0.0854 |
| 3 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=not religious at all | changed | -0.0475 | -0.1329 |
| 4 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=neither agree nor disagree; `immjobs`=disagree; `immwlfare`=neither agree nor disagree | changed | -0.0013 | -0.1342 |
| 5 | Which of the following best describes what you believe about God? | DIRECT | `god`=don't know, no way to find out; `biblev`=inspired word; `bible`=inspired word; `biblenv`=inspired word | changed | +0.0294 | -0.1049 |
| 6 | If someone in your community wrote a book against all churches and religion, would you support removing that book from the library or not? | DIRECT | `libathy`=not remove; `libath`=not remove | changed | -0.0003 | -0.1051 |
| 7 | On a scale from 0 to 100, where 0 means very unfavorable and 100 means very favorable, how would you rate Donald Trump? | DIRECT | `ratechall124`=60.0 | changed | +0.0188 | -0.0863 |
| 8 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=neither favor nor oppose | changed | +0.0005 | -0.0858 |
| 9 | Should a person who wants to say that Black people are genetically inferior be allowed to make a speech in your community, or should they not be allowed to speak? | DIRECT | `spkracy`=not allowed; `spkrac`=yes, allowed to speak | changed | -0.0006 | -0.0864 |
| 10 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all; `teensex`=almost always wrong | changed | -0.0090 | -0.0954 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
