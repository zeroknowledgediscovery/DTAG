# M01 implementation and verification

Base: `b6f20cf5e87af9d23ef947de43355934da17980c` (`origin/dev`, fetched 2026-10-24).
Branch: `experiment/prolific-human-study`. Obtain the checked-out implementation SHA with `git rev-parse HEAD` (a report cannot contain its own Git commit hash).

The separate `backend/human_study` package uses `World`, `ModelContext`, wave-specific polar geometry, `one_step_geometry`, `native_extension_indices`, the existing opinion classifier, and the core question generator/mapper. It does not instantiate a synthetic respondent. Human observations are validated exact categories, never inferred from persona text, drawn, or evicted. All policies use the same explicitly configured opinion bank; right/left/neutral rank expected displacement, random uses persisted PCG64 state. Ties use ascending variable IDs. Outcomes are reserved. Optional missingness is recorded separately.

`instrument.py` constructs a 13-item baseline, separate held-out outcomes and a limited intervention bank from actual model categories and semantic map text. It refuses to guess category labels and produces `reviewed=false`. This generated instrument needs substantive investigator/ethics review. It is a conditional predictive phenotype, not a validated persona class. The scalar pole-relative statistic is not a measure of human persuasion or belief change.

Validation performed:

```
PATH=/workspace/.venv/bin:$PATH pytest -q human_study/tests/test_human_engine.py
7 passed, 1 skipped

DTAG_TEST_OFFLINE=1 DTAG_WEB_DATA_DIR=/workspace/.cache/dtag/webapp \
  /workspace/.venv/bin/pytest -q webapp/tests optimizer/tests --disable-warnings
141 passed, 16 skipped
```

Tests patch synthetic persona/answer functions to raise, replay recorded 20-answer trajectories for all four policies, compare policy rankings with reference geometry, validate exclusions/categories/repeats, and exercise generated wording/mapping fallback. The native C++ extension was compiled for this machine's Python 3.12 and imported successfully. The prebuilt Python 3.13 extension remains unchanged.

Real-native GSS validation is pending: the environment proxy returned HTTP 403 for `storage.googleapis.com`, which hosts the checksum-verified release. That domain was saved to the environment draft. Native integration tests skip explicitly when the artifact is missing. No live OpenAI request was made. No survey instrument, clinical/persona validity, live LLM neutrality, or real human effect has been established by fixture tests. Model distribution licensing needs investigator review (`native/lsm_runtime/LICENSE` covers the runtime; public availability alone does not settle survey/model reuse terms).

Next milestone adds transactional durable state, immutable research exports and the isolated participant UI. Existing simulator source and behavior remain untouched.
