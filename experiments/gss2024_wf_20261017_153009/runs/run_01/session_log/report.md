# DTAG session report — Respondent run01

- Exported: 2026-10-17T19:31:08+00:00  ·  session `568a3948ac59410696d8dab349065cdd`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:30:11+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592279, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 6 variables (0 forced by geography/time); dropped LLM assignments: 2. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0402 → current -0.0742 (change -0.0340)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q6 -0.0188; Q8 -0.0136; Q9 -0.0106; Q7 +0.0085; Q10 +0.0071

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=not fired | changed | -0.0064 | -0.0466 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=not allowed; `librac`=not remove; `colrac`=yes, allowed to teach | changed | -0.0055 | -0.0521 |
| 3 | If a Muslim religious leader wanted to give a speech in your community expressing hatred toward the United States, do you think he should be allowed to speak or not? | DIRECT | `spkmslmy`=not allowed; `spkmslm`=not allowed; `libmslmy`=remove; `libmslm`=not remove | changed | +0.0010 | -0.0511 |
| 4 | Do you agree or disagree that people like you and your family have a good chance of improving your standard of living in America? | DIRECT | `goodlife`=agree | changed | +0.0031 | -0.0480 |
| 5 | To what extent do you agree or disagree with the statement: You would agree more with people if they were more like Americans? | DIRECT | `belikeus`=disagree | changed | +0.0013 | -0.0467 |
| 6 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0188 | -0.0656 |
| 7 | Do you think we are spending too much, about the right amount, or too little on improving and protecting the nation's health? | DIRECT | `natheal`=about right | changed | +0.0085 | -0.0571 |
| 8 | Do you think we are spending too much, too little, or about the right amount on help with childcare? | DIRECT | `natchld`=too little | changed | -0.0136 | -0.0707 |
| 9 | Do you think we are spending too much, too little, or about the right amount on solving the problems of big cities? | DIRECT | `natcity`=about right; `natcityy`=about right | changed | -0.0106 | -0.0813 |
| 10 | What is your rating of Kamala Harris on a scale from 0 to 100, where 0 means the lowest and 100 means the highest? | DIRECT | `ratechall224`=5.0 | changed | +0.0071 | -0.0742 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
