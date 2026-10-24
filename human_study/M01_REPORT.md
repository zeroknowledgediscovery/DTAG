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

The initial GSS download was blocked by proxy HTTP 403. After the network configuration changed, the v0.2.1 artifact downloaded with SHA256 verification into `/workspace/.cache/dtag/models/gss/gss_2024`. The real-native index/withheld-prediction test passed. The final engine run reported **12 passed in 59.67 seconds**, including four native 20-step recorded-answer policy/replay tests with direct native index equality. The builder validated 44 instrument items against actual native categories and map coverage: 13 baseline, 28 intervention, three outcomes. `config/study.example.yaml` contains the full native-validated draft with `reviewed=false`. A complete 36-answer GSS session also completed through the existing DTAG mock LLM wording/mapping interface and local outbox archive, producing 75 immutable objects. Further native regression results are recorded in M02_REPORT.md.

No live OpenAI request was made. No survey instrument, clinical/persona validity, live LLM neutrality, ethics approval or human effect has been established. Model distribution licensing needs investigator review (`native/lsm_runtime/LICENSE` covers the runtime; public availability alone does not settle survey/model reuse terms).

Next milestone adds transactional durable state, immutable research exports and the isolated participant UI. Existing simulator source and behavior remain untouched.
