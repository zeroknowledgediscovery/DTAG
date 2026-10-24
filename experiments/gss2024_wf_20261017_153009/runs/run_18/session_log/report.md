# DTAG session report — Respondent run18

- Exported: 2026-10-17T19:46:55+00:00  ·  session `69a350315b3c4e6e8e7d001c97b95dbf`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:46:03+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592296, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 5 variables (0 forced by geography/time); dropped LLM assignments: 2. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0402 → current +0.0369 (change +0.0772)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q6 +0.0618; Q1 +0.0417; Q8 +0.0214; Q7 -0.0188; Q2 -0.0150

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=not allowed; `colcomy`=not fired | changed | +0.0417 | +0.0015 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=yes, allowed to speak | changed | -0.0150 | -0.0135 |
| 3 | If someone in your community wrote a book against churches and religion, would you support removing that book from the library or not? | DIRECT | `libathy`=not remove; `libath`=not remove | changed | -0.0036 | -0.0171 |
| 4 | Do you agree or disagree that people like you and your family have a good chance of improving your standard of living in America? | DIRECT | `goodlife`=agree | changed | +0.0031 | -0.0140 |
| 5 | To what extent do you agree or disagree with the statement: You would agree more with people if they were more like Americans? | DIRECT | `belikeus`=neither agree nor disagree | changed | +0.0038 | -0.0102 |
| 6 | If a Muslim religious leader wanted to give a speech in your community expressing hatred toward the United States, do you think he should be allowed to speak or not? | DIRECT | `spkmslmy`=not allowed; `spkmslm`=not allowed; `libmslmy`=remove; `libmslm`=remove | changed | +0.0618 | +0.0517 |
| 7 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0188 | +0.0328 |
| 8 | Do you think sexual relations between two adults of the same sex are always wrong, almost always wrong, wrong only sometimes, or not wrong at all? | DIRECT | `homosex`=always wrong | changed | +0.0214 | +0.0542 |
| 9 | Do you think that sex before marriage is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for teenagers aged 14 to 16? | DIRECT | `teensex`=wrong only sometimes | changed | -0.0081 | +0.0461 |
| 10 | Do you think we are spending too much, about the right amount, or too little on improving and protecting the nation's health? | DIRECT | `natheal`=too little | changed | -0.0091 | +0.0369 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
