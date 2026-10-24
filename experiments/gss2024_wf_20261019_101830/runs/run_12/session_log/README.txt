DTAG session archive (dtag-session-archive/1)

The history covers the questions asked since the session was created or last reset.

  report.md                  human-readable summary (persona, model, settings, ideology, all questions)
  manifest.json              versions, model checksum, counts and a checksum of every file
  session.json               complete engine export (the authoritative full record)
  settings.json              profile, run configuration, LLM, requested and resolved geography/time
  persona.txt                the persona description used
  persona_initialization.json  LLM persona assignments (raw), dropped ones, rationale, forced assignments
  initial_state.csv          initial survey state (variable, value, survey question)
  final_state.csv            survey state after the last question
  questions.csv              one row per question (mapping, survey answers, state updates, ideology, timings)
  questions.jsonl            one JSON record per question with the answer, evidence and full distributions
  ideology_trajectory.csv    ideology after every question (step 0 = initial state)
  ideology.svg               chart of the trajectory
  state_changes.csv          every state change, with the previous value
  poles.csv                  the polar-vector file used for the ideology index (if any)
  sequence.json              the latest question sequence run since the last reset (if any)
