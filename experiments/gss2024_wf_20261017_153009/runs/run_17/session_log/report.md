# DTAG session report — Respondent run17

- Exported: 2026-10-17T19:46:01+00:00  ·  session `88a76a18d17a4f1ca14ecf16b395b773`  ·  DTAG 0.2.0.dev1 (commit b2ef25d63336319005782a0c74163244e20ebbbd)
- History since: 2026-10-17T19:45:08+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 511592295, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 8 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0400 → current -0.0567 (change -0.0167)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q3 +0.0453; Q2 -0.0224; Q7 -0.0209; Q9 +0.0190; Q6 -0.0187

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach in a college or university? | DIRECT | `colrac`=not allowed; `colmslm`=not allowed; `colath`=yes, allowed to teach; `colcomy`=not fired | changed | -0.0063 | -0.0462 |
| 2 | Do you think a person who says that Black people are genetically inferior should be allowed to speak in your community or not? | DIRECT | `spkracy`=not allowed; `spkrac`=yes, allowed to speak; `librac`=not remove; `colrac`=not allowed | changed | -0.0224 | -0.0686 |
| 3 | If someone in your community wrote a book against churches and religion, would you support removing that book from the library or not? | DIRECT | `libathy`=not remove; `libath`=remove | changed | +0.0453 | -0.0233 |
| 4 | How likely do you think it is that a white person will not get a job or promotion while an equally or less qualified black person gets one instead? | DIRECT | `discaff`=somewhat likely; `affrmact`=not strongly opposes; `fehire`=agree | changed | +0.0042 | -0.0191 |
| 5 | How much confidence do you have in the people running the U.S. Supreme Court: a great deal, only some, or hardly any? | DIRECT | `conjudge`=a great deal | changed | -0.0050 | -0.0241 |
| 6 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=not wrong at all | changed | -0.0187 | -0.0428 |
| 7 | Do you think sexual relations between two adults of the same sex are always wrong, almost always wrong, wrong only sometimes, or not wrong at all? | DIRECT | `homosex`=not wrong at all | changed | -0.0209 | -0.0637 |
| 8 | Do you think we are spending too much, about the right amount, or too little on improving and protecting the nation's health? | DIRECT | `natheal`=too little; `nathealy`=too little | changed | -0.0105 | -0.0741 |
| 9 | What is your rating of Kamala Harris on a scale from 0 to 100, where 0 means the lowest and 100 means the highest? | DIRECT | `ratechall224`=0.0 | changed | +0.0190 | -0.0551 |
| 10 | How much confidence do you have in the people running Congress: a great deal, only some, or hardly any? | DIRECT | `conlegis`=only some | changed | -0.0015 | -0.0567 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
