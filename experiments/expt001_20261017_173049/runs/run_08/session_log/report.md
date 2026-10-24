# DTAG session report — Respondent run08

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-17T21:34:32+00:00  ·  session `406ce31812cd488e8371057186a5c6ed`  ·  DTAG 0.2.0.dev1 (commit 343e4ba73314a05ff46fe1d9450d1d3d3b13a25f)
- History since: 2026-10-17T21:34:06+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 632680337, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 8 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0400 → current -0.0139 (change +0.0261)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q2 +0.0264; Q1 +0.0189; Q4 -0.0181; Q5 -0.0105; Q3 +0.0094

## Questions (5)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=always wrong; `teensex`=always wrong | changed | +0.0189 | -0.0211 |
| 2 | Do you think a person who is against all churches and religion should be allowed to teach in a college or university? | DIRECT | `colath`=not allowed | changed | +0.0264 | +0.0053 |
| 3 | If a Muslim religious leader wanted to give a speech in your community expressing hatred of the United States, should he be allowed to speak or not? | DIRECT | `spkmslmy`=not allowed; `spkmslm`=not allowed | changed | +0.0094 | +0.0147 |
| 4 | How spiritual do you consider yourself to be: very spiritual, moderately spiritual, slightly spiritual, or not spiritual at all? | DIRECT | `sprtprsn`=slightly spiritual | changed | -0.0181 | -0.0034 |
| 5 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=slightly religious | changed | -0.0105 | -0.0139 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
