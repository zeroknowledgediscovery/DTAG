# DTAG session report — Respondent run09

- Exported: 2026-10-17T19:38:28+00:00  ·  session `1efc5f0dee7042bc9468eeb96036ec67`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:37:34+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592287, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 6 variables (0 forced by geography/time); dropped LLM assignments: 1. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0402 → current +0.0251 (change +0.0653)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q1 +0.0476; Q2 +0.0415; Q3 +0.0403; Q7 -0.0208; Q6 -0.0188

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=not fired | changed | +0.0476 | +0.0073 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=not allowed; `librac`=remove; `colrac`=not allowed | changed | +0.0415 | +0.0488 |
| 3 | If a Muslim religious leader wanted to give a speech in your community expressing hatred toward the United States, do you think he should be allowed to speak or not? | DIRECT | `spkmslmy`=yes, allowed to speak; `spkmslm`=not allowed; `libmslmy`=remove; `libmslm`=remove | changed | +0.0403 | +0.0891 |
| 4 | Do you agree or disagree that people like you and your family have a good chance of improving your standard of living in America? | DIRECT | `goodlife`=agree | changed | +0.0031 | +0.0923 |
| 5 | To what extent do you agree or disagree with the statement: You would agree more with people if they were more like Americans? | DIRECT | `belikeus`=disagree | changed | +0.0013 | +0.0936 |
| 6 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0188 | +0.0747 |
| 7 | Do you think sexual relations between two adults of the same sex are always wrong, almost always wrong, wrong only sometimes, or not wrong at all? | DIRECT | `homosex`=not wrong at all | changed | -0.0208 | +0.0539 |
| 8 | Do you agree or disagree that homosexual couples should have the right to marry? | DIRECT | `marsame`=strongly agree; `marsamey`=strongly agree | changed | -0.0139 | +0.0400 |
| 9 | If someone wanted to make a speech in your community against churches and religion, should they be allowed to speak or not? | DIRECT | `spkathy`=yes, allowed to speak; `spkath`=yes, allowed to speak | changed | -0.0080 | +0.0320 |
| 10 | How often do you think people try to take advantage rather than be fair? | DIRECT | `befair`=try to be fair most of the time; `fair`=would try to be fair; `fairv`=depends (phone mode only: volunteered); `fairnv`=would take advantage of you | changed | -0.0069 | +0.0251 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
