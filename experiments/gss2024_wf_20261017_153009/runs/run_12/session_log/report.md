# DTAG session report — Respondent run12

- Exported: 2026-10-17T19:41:20+00:00  ·  session `725a7c2b5cf8429a8a1b291514ed8dcf`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:40:25+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592290, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 6 variables (0 forced by geography/time); dropped LLM assignments: 1. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0402 → current +0.0778 (change +0.1181)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q1 +0.0825; Q3 +0.0388; Q10 -0.0170; Q6 +0.0156; Q5 +0.0114

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=not allowed; `colcomy`=yes, fired | changed | +0.0825 | +0.0423 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=not allowed; `librac`=not remove; `colrac`=not allowed | changed | +0.0052 | +0.0475 |
| 3 | If a Muslim religious leader wanted to give a speech in your community expressing hatred toward the United States, do you think he should be allowed to speak or not? | DIRECT | `spkmslmy`=not allowed; `spkmslm`=not allowed; `libmslmy`=not remove; `libmslm`=remove | changed | +0.0388 | +0.0863 |
| 4 | Do you agree or disagree that people like you and your family have a good chance of improving your standard of living in America? | DIRECT | `goodlife`=strongly disagree | changed | +0.0015 | +0.0878 |
| 5 | How much confidence do you have in the people running the U.S. Supreme Court: a great deal, only some, or hardly any? | DIRECT | `conjudge`=hardly any | changed | +0.0114 | +0.0992 |
| 6 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=always wrong | changed | +0.0156 | +0.1148 |
| 7 | Would you say you are very spiritual, moderately spiritual, slightly spiritual, or not spiritual at all? | DIRECT | `sprtprsn`=moderately spiritual | changed | -0.0073 | +0.1075 |
| 8 | Do you think we are spending too much, about the right amount, or too little on improving and protecting the nation's health? | DIRECT | `natheal`=too little | changed | -0.0094 | +0.0981 |
| 9 | Do you think we are spending too much, too little, or about the right amount on improving the conditions of Black people? | DIRECT | `natrace`=too little; `natracey`=about right | changed | -0.0033 | +0.0948 |
| 10 | Do you think that on average, Black people have worse jobs, income, and housing than White people? | DIRECT | `racdif5x`=no; `racdif1`=yes; `racdif1x`=yes; `racdif2`=yes | changed | -0.0170 | +0.0778 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
