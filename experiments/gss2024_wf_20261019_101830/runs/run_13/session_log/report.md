# DTAG session report — Respondent run13

_DTAG · ZeD Lab, University of Kentucky · ishanu_ch@uky.edu_

- Exported: 2026-10-19T14:29:53+00:00  ·  session `b1baf9a702fb4d5bae95e4dc3a4f0f50`  ·  DTAG 0.2.0.dev1 (commit 918aefec0eec65092da526f7cda7d4f401f0a932)
- History since: 2026-10-19T14:29:04+00:00 (resets so far: 0)
- Model: `gss/gss_2024` (release v0.2.1, sha256 00879d10a99f…), map `gss/gss_2024_map.csv`
- Country: United States  ·  year/wave: 2024  ·  date: —
- Response mode `draw`, semantic fallback `update_state`, seed 817206057, LLM `gpt-4.1-mini` (openai)

## Persona

> 22 year old white female without children in urban New York, regular news consumer, working in retail, highly progressive
> Country context: United States
> Survey year: 2024

Initial survey state: 7 variables (0 forced by geography/time); dropped LLM assignments: 0. Details in `persona_initialization.json` and `initial_state.csv`.

## Ideology

- Initial -0.0893 → current +0.0487 (change +0.1380)
- Poles: `gss_2024_polar_vectors.csv` (27 items); negative is nearer the L pole, positive nearer the R pole. Chart: `ideology.svg`.
- Largest moves: Q1 +0.0582; Q2 +0.0453; Q8 +0.0137; Q3 +0.0124; Q7 +0.0094

## Questions (10)

| Q | Question | Mapping | Survey answers | State | ΔI | I |
|---:|---|---|---|---|---:|---:|
| 1 | Do you think a person like this should be allowed to teach at a college or university? | DIRECT | `colrac`=yes, allowed to teach; `colmslm`=not allowed; `colath`=not allowed; `colcomy`=not fired | changed | +0.0582 | -0.0310 |
| 2 | How religious do you consider yourself to be: very religious, moderately religious, slightly religious, or not religious at all? | DIRECT | `relpersn`=moderately religious | changed | +0.0453 | +0.0143 |
| 3 | How important is it to you to be a Christian? | DIRECT | `amchrstn`=fairly important | changed | +0.0124 | +0.0267 |
| 4 | To what extent do you agree or disagree with the statement that immigrants take jobs away? | DIRECT | `immjobs1`=disagree; `immjobs`=disagree; `immwlfare`=disagree | changed | -0.0059 | +0.0208 |
| 5 | Do you agree or disagree that the United States would be a better country if religion had less influence? | DIRECT | `religinf`=strongly disagree | changed | +0.0057 | +0.0264 |
| 6 | Do you strongly oppose, oppose, neither favor nor oppose, favor, or strongly favor a close relative marrying a Hispanic or Latino person? | DIRECT | `marhisp`=neither favor nor oppose | changed | +0.0005 | +0.0269 |
| 7 | Do you think we are spending too much, too little, or about the right amount on supporting scientific research? | DIRECT | `natsci`=about right | changed | +0.0094 | +0.0363 |
| 8 | Do you think it is always wrong, almost always wrong, wrong only sometimes, or not wrong at all for a man and a woman to have sexual relations before marriage? | DIRECT | `premarsx`=wrong only sometimes | changed | +0.0137 | +0.0500 |
| 9 | How would you rate Joe Biden on a scale where you can choose from the following numbers: 0, 2, 20, 25, 29, 30, 45, 55, 60, 65, 75, 85, 90, 99, or 100? | DIRECT | `rateincumb24`=100.0 | changed | -0.0044 | +0.0456 |
| 10 | Do you think society has gone too far, not far enough, or about far enough in accepting people? | DIRECT | `acpttg`=too far | changed | +0.0031 | +0.0487 |

Full answers, evidence and distributions: `questions.jsonl`; state progression: `state_changes.csv`.
