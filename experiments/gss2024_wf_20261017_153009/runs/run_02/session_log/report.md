# DTAG session report — Respondent run02

- Exported: 2026-10-17T19:32:00+00:00  ·  session `a8b675aec8724f8393180efaa052dfac`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:31:10+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592280, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 7 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0400 → current +0.0914 (change +0.1314)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q1 +0.0401; Q2 +0.0371; Q7 +0.0208; Q8 +0.0182; Q6 +0.0157

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=not allowed; `colcomy`=yes, fired | changed | +0.0401 | +0.0001 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=not allowed; `librac`=remove; `colrac`=not allowed | changed | +0.0371 | +0.0372 |
| 3 | Do you agree or disagree that people like you and your family have a good chance of improving your standard of living in America? | DIRECT | `goodlife`=agree | changed | +0.0032 | +0.0404 |
| 4 | To what extent do you agree or disagree with the statement: You would agree more with people if they were more like Americans? | DIRECT | `belikeus`=disagree | changed | +0.0013 | +0.0416 |
| 5 | How much confidence do you have in the people running the U.S. Supreme Court: a great deal, only some, or hardly any? | DIRECT | `conjudge`=hardly any | changed | +0.0122 | +0.0538 |
| 6 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=always wrong | changed | +0.0157 | +0.0695 |
| 7 | Would you say you are very spiritual, moderately spiritual, slightly spiritual, or not spiritual at all? | DIRECT | `sprtprsn`=very spiritual | changed | +0.0208 | +0.0903 |
| 8 | Do you think sexual relations between two adults of the same sex are always wrong, almost always wrong, wrong only sometimes, or not wrong at all? | DIRECT | `homosex`=always wrong | changed | +0.0182 | +0.1085 |
| 9 | Do you think we are spending too much, about the right amount, or too little on improving and protecting the nation's health? | DIRECT | `natheal`=too little | changed | -0.0091 | +0.0994 |
| 10 | Do you think a woman should be allowed to end her pregnancy if her own health is seriously at risk? | DIRECT | `abhlthg`=yes; `abhlth`=yes | changed | -0.0080 | +0.0914 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
