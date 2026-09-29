# DTAG Web Application — Implementation Plan

This document was written before the web application code, from a reading of
the `native-lsm-clean` branch. It records what the native DTAG runtime does
today, which parts are extracted into reusable objects, and how the web
application sits on top of them without becoming a second DTAG implementation.

---

## 1. Current native DTAG call flow

```text
dtag --profile gss2024_cm                          (dtag/cli.py)
  └─ scripts/interactive.py                        profile → argv
       └─ subprocess: scripts/pipeline_localized.py
            └─ monkeypatches pipeline.build_forced_assignments
            └─ pipeline.main()
                 1. load_model(model_dir)            → NativeLSMBackend (persistent dtag_lsm.Runtime)
                 2. load_var_map(map) ∩ features
                 3. polar vectors → sL, sR, dLR = qdistance(sL, sR)
                 4. possible responses (assets/*.possible.*.json cache)
                 5. persona text += continent / country / year context
                 6. lexical scoring of variables vs persona → offered variables
                 7. LLM: persona → survey assignments (validated against support)
                 8. forced assignments: year / categorical country / coordinates
                 9. state = validated persona assignments + forced assignments
                10. ideology0 = I(state) if polar vectors are compatible
                per question (_run_one):
                  a. lexical_prefilter (content-word gate; may return nothing)
                  b. LLM variable selection (may return nothing)
                  c. native predict_distributions(state, targets)   ← anchor
                  d. max / draw response  (seed + query_idx)
                  e. state update (+ state_keep eviction)
                  f. ideology I(state) via distances_to_state
                  g. LLM answer rendering from anchors
                  fallback (_run_semantic_fallback) when a/b fail:
                  off | answer_only | update_state, embedding retrieval +
                  LLM bridge selection, native prediction, optional state update
                  no match (_record_no_match): state preserved, ideology carried
                11. write meta.json / final_state.json / ideology.csv / questions.csv
```

Eurobarometer uses `scripts/eurobarometer_native.py`, which resolves a ZA
identifier (explicitly, or from a fieldwork date through
`scripts/eurobarometer_dates.py`), resolves the ZA map, and then runs the same
`pipeline_localized.py` subprocess.

## 2. `NativeLSMBackend` / `dtag_lsm.Runtime` lifecycle

`scripts/model_backend.py::NativeLSMBackend.__init__` reads the source-map
shards (feature names and categorical support), discovers the usable trees
(those with non-empty support), and constructs one `dtag_lsm.Runtime` with
preload enabled. The runtime keeps the binary trees and source-map dictionaries
in memory until the Python object is garbage collected.

Measured in this container for GSS 2024 (813 features, 812 usable trees):

```text
preload                 6.6 s once
predict[immassim]       0.0004 s
qdistance               0.07 s
two pole distances      0.10 s
```

The C++ binding releases the GIL during inference. Its internal thread safety
for *concurrent* calls on one runtime has not been stress-tested, so the web
layer serialises inference on a shared model with a per-model lock (§6).

## 3. What `pipeline.py` owns today

`main()` is a single 700-line function. It owns argument parsing, logging/tee,
report paths, all session initialisation, and three closures holding the
per-question algorithm (`_run_one`, `_run_semantic_fallback`,
`_record_no_match`) that mutate closure variables (`state`, `records`,
`ideology_series`, `question_series`). Nothing is reusable without running
`main()` as a process and scraping stdout.

## 4. What is extracted

New module **`scripts/dtag_session.py`** (scientific core, outside `webapp/`):

* `SessionConfig` — every `pipeline.py` runtime parameter with the same defaults.
* `ModelContext` — the model-level data a session needs: backend, feature set,
  index map, possible responses, filtered map, polar-vector geometry. Built once
  and shareable between sessions (read-only after construction).
* `DTAGSession` — the body of `main()` steps 5–10 plus the three closures,
  converted line-for-line into methods on an object that owns `state`,
  `records`, `ideology_series`, `question_series`.
  `session.ask(question)` returns a structured result that contains the exact
  legacy `records` entry *and* richer evidence (full native distributions,
  survey wording, map provenance, mapping class, before/after ideology, state
  snapshot).
* `session.reset()` restores the initialised state snapshot without another
  LLM persona call or model reload.

The OpenAI client is injected (`client_factory`) instead of being constructed
inline, so tests and demos can use a deterministic mock without changing the
algorithm. The LLM helper functions (`llm_select_variables`, ...) remain in
`pipeline.py` and are called unchanged.

New module **`scripts/dtag_engine.py`**:

* model catalog (manifest + installed + maps + configured models),
* map catalog and model→map conventions,
* `ModelRegistry` — process-level cache of loaded models + install jobs,
* profile resolution (shared with `interactive.py`),
* geography/time/ideology capability description,
* Eurobarometer routing wrapper around `eurobarometer_dates.py`,
* `DTAGEngine.create_session(profile=..., overrides=...)`.

`scripts/fetch_models.py` is refactored into reusable functions
(`load_manifest`, `fetch_one(..., progress=...)`, `installed`) with the CLI kept
intact; extraction gains explicit path-traversal checks on the fallback path.

## 5. CLI equivalence

`pipeline.main()` keeps its argument surface, log/report files, printed
sections, and the same `meta.json` record schema; it now builds a
`ModelContext` + `DTAGSession` and prints the returned results.
`pipeline_localized.py` continues to monkeypatch `build_forced_assignments`;
`DTAGSession` resolves `core.build_forced_assignments` at call time so the
patch still applies. The web engine passes the localized function explicitly.

Equivalence is verified by running the pre-refactor `pipeline.py` and the new
one with the same deterministic mock OpenAI client against the real GSS 2024
native model, and comparing the `meta.json` records and final state.

Deliberate, visible changes:

* the per-question timing key `qnet_predict` is renamed `native_predict`
  (`semantic_qnet_predict` → `semantic_native_predict`). This was only a
  historical label; nothing downstream reads it.
* semantic-fallback embeddings for a map are cached in memory per model context
  instead of re-reading the JSON cache for each fallback question (same values).
* `pipeline_localized.find_categorical_country_assignment` gains a third,
  conservative matching pass for labels of the form `"FR - France"` (the
  Eurobarometer `country` feature). It applies only when exactly one support
  value matches; otherwise conditioning stays contextual and is reported as such.
  This changes CLI behaviour only in cases where country was previously *not*
  hard-conditioned.
* The matcher then gains two further passes, used only when the original ones
  find nothing and only for a unique match: the Eurobarometer ISO 3166 variable
  `isocntry`, and map-labelled `NATION` variables of older waves (passed by
  `DTAGSession` as `hint_features`, with native spellings such as
  `DEUTSCHLAND`). GSS/Afrobarometer/WVS results are unchanged (verified: the
  GSS old-vs-new CLI comparison stays identical).

## 6. Model catalog, download and memory cache

Resolution (identical for CLI and web; `fetch_models.default_root()` now
delegates to `dtag_paths.model_root()` so both agree):

```text
model key (validated against manifest ∪ installed ∪ configured)
  → DTAG_MODEL_ROOT | populated <repo>/models/lsm | ~/.cache/dtag/models
  → installed? (source_maps/ + trees/binary/)
  → else manifest → download .tar.zst → SHA256 → safe extract → validate
  → NativeLSMBackend (persistent runtime) → ModelRegistry.loaded[key]
```

`ModelRegistry` keeps `loaded: dict[str, LoadedModel]` keyed by canonical model
key. One lock per key guarantees one download and one load even when several
sessions request the same model simultaneously. States exposed to the API:
`not_installed → downloading → verifying → extracting → installed → loading →
loaded`, or `error`. Install jobs run in a background thread with byte
progress; session creation waits on the same job instead of starting another.

`LoadedModel` holds the backend behind a lock-guarded proxy, possible
responses, and caches keyed by map path (filtered map + provenance), polar
vector set (sL, sR, dLR) and embedding model.

## 7. Session-state isolation

Every `DTAGSession` owns its own `OrderedDict` state, initial snapshot,
records, ideology series, question series, persona assignments and forced
assignments. `ModelContext` objects are shared but treated as immutable after
construction. Draw-mode randomness is `default_rng(seed + query_idx)` per
question (as in the CLI), so there is no shared RNG state. A per-session lock
serialises concurrent questions on the same session. The web session store is
an in-memory `SessionStore` with an interface that a Redis/DB store could
implement later.

## 8. Maps and polar vectors

Maps are validated against the repository inventory (`maps/**.csv`), never a
browser-supplied path. Canonical model→map rules:

```text
gss/gss_YYYY                  → maps/gss/gss_YYYY_map.csv
afrobarometer/rN              → maps/afromap/afrobarometer_rN_map.csv
wvs/wvs7_pooled               → maps/wvs7_variable_question_map.csv
eurobarometer/ZAxxxx_v...     → maps/eurobarometer/ZAxxxx_map.csv
```

Map provenance columns (`map_provenance`, `fallback_*`) are loaded per variable
and attached to anchors.

Polar vectors are registered with the families they are valid for. The only
current set, `assets/polar_vectors/polar_vectors.csv`, is registered for
`gss` only; requesting it for WVS/Afrobarometer/Eurobarometer is rejected. Even
for GSS, ideology is enabled only if the vectors overlap the model and
`dLR` is finite and positive (the existing pipeline rule).

## 9. API

FastAPI, `/docs` for OpenAPI. Endpoints:

```text
GET  /api/health
GET  /api/readiness                     (cached; ?refresh=true)
GET  /api/profiles                      configured profiles + custom profiles
GET  /api/profiles/{name}
POST /api/profiles                      save custom profile (webapp data dir)
DELETE /api/profiles/{name}             custom only
POST /api/profiles/validate             warnings for a draft profile
GET  /api/models                        full catalog (?family=)
GET  /api/models/{key}
POST /api/models/{key}/install          starts/returns install job
GET  /api/models/{key}/status
GET  /api/maps
GET  /api/eurobarometer/waves           registry + installed models
GET  /api/eurobarometer/resolve         ?date=YYYY-MM-DD | ?year= | ?za=
POST /api/sessions
GET  /api/sessions
GET  /api/sessions/{id}
POST /api/sessions/{id}/questions
POST /api/sessions/{id}/reset
DELETE /api/sessions/{id}
GET  /api/sessions/{id}/export?format=json|csv
```

Browser-supplied profile fields are whitelisted: persona, country, continent,
year, date, za, semantic_fallback, resp_mode, seed and bounded numeric runtime
parameters. Model keys are validated against the catalog; map keys against the
map inventory; polar sets against the registry. No paths, commands or URLs are
accepted.

## 10. Frontend

React + TypeScript + Vite in `webapp/frontend`, built into
`webapp/frontend/dist` and served by FastAPI in production (one container, one
port). Three regions:

* left: profile picker, WHO/WHERE/WHEN, survey/model, fallback, response mode,
  advanced parameters, model install status/progress, start/reset/save;
  "Create profile" builder with family → model → template → map → persona →
  geography → time → ideology → fallback → response mode → save.
* centre: chat with an expandable "Model evidence" panel per answer.
* right: survey/model/wave/country/conditioning summary, ideology index and
  SVG trajectory, collapsible current survey state, session timeline
  (DIRECT / SEMANTIC·ANSWER ONLY / SEMANTIC·STATE UPDATE / NO MATCH).

## 11. Eurobarometer routing

The routing code reads fieldwork dates only from a two-column registry
(`ZA,dd.mm.yyyy - dd.mm.yyyy`) via `eurobarometer_dates.load_registry`. The
default `configs/eurodates.csv` is **not tracked in this repository**. The
engine therefore looks for the registry at `DTAG_EURODATES` (explicit path) or
`configs/eurodates.csv` if one is added later, and:

* registry present: date → `resolve_exact_date` (unique ordinary interval
  only; ambiguous/no-coverage dates are errors, never nearest-wave guesses);
  year → list of candidate waves, never auto-selection;
* registry absent: date routing reports "unavailable" and the UI offers explicit
  ZA selection over the 207 catalog models.

The resolved ZA, fieldwork interval, model key and map are returned in the
session's temporal conditioning metadata.

## 12. Deployment

* `webapp/run.sh` — local source-checkout launch (builds the frontend if needed).
* `dtag-web` console entry point — launches from a direct Git install.
* `webapp/Dockerfile`, `docker-compose.yml`, `.env.example` — image contains
  code, maps, configs, native runtime and built frontend; models live on a
  mounted volume (`DTAG_MODEL_ROOT=/data/models`); no credentials in the image.
* `setup.py` ships `webapp/backend` and `webapp/frontend/dist` as runtime data
  and adds `fastapi`/`uvicorn` dependencies.

## 13. Scientific-equivalence risks

| Risk | Mitigation |
|---|---|
| Refactor changes persona init or question flow | line-by-line port; old-vs-new CLI comparison with a deterministic mock LLM on a real native model |
| Shared model mutated by one session | `ModelContext` read-only; state per session; test asserts isolation |
| Concurrent native calls on one runtime | per-model lock around predict/qdistance/distances |
| Reusing GSS polar vectors elsewhere | family-registered polar sets; rejected otherwise |
| Overclaiming geography | conditioning metadata derived from forced assignments actually placed in state |
| Year treated as EB wave | year never routes; date requires registry and a unique interval |
| Fallback maps presented as exact | per-anchor map provenance in evidence and export |
| LLM replacing inference | anchors only from `predict_distributions`; LLM only selects variables and renders prose |
