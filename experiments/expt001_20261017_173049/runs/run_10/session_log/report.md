# DTAG session report — Respondent run10

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-17T21:35:28+00:00  ·  session `666ffbb0e8bd4bf7b20c48b8445a9a35`  ·  DTAG 0.2.0.dev1 (commit 343e4ba73314a05ff46fe1d9450d1d3d3b13a25f)
- History since: 2026-10-17T21:35:03+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 632680339, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 5 variables (0 forced by geography/time); dropped LLM assignments: 2. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0402 → current -0.1321 (change -0.0918)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q2 -0.0236; Q4 -0.0225; Q1 -0.0188; Q5 -0.0177; Q3 -0.0092

## Questions (5)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0188 | -0.0591 |
| 2 | Do you think a person who is against all churches and religion should be allowed to teach in a college or university? | DIRECT | `colath`=yes, allowed to teach | changed | -0.0236 | -0.0827 |
| 3 | Do you think we are spending too much, too little, or about the right amount on improving and protecting the nation's health? | DIRECT | `natheal`=too little | changed | -0.0092 | -0.0919 |
| 4 | Do you agree or disagree that same-sex couples should have the right to marry? | DIRECT | `marsamey`=strongly agree; `marsame`=strongly agree | changed | -0.0225 | -0.1144 |
| 5 | Do you think sexual relations between two consenting adults of the same sex are always wrong, almost always wrong, sometimes wrong, or not wrong at all? | DIRECT | `homosex`=not wrong at all | changed | -0.0177 | -0.1321 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
