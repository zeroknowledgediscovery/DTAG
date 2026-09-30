# DTAG Web Application

> **New here? Start with [QUICKSTART.md](QUICKSTART.md)** — install, run and use
> the web app in five steps. This page is the full reference.
> **Taking over development or deploying it?** Read [HANDOFF.md](HANDOFF.md).

A browser workbench and HTTP API for **DTAG — Digital Twin Anchored Generation**
over the native Large Science Model (LSM) corpus (35 GSS + 9 Afrobarometer +
1 WVS7 + 207 Eurobarometer = 252 native models, 252 semantic maps).

The web application is a thin layer over the same scientific core the command
line uses:

```text
native LSM (dtag_lsm.Runtime, persistent)      scripts/model_backend.py
        ↑
DTAGSession  (respondent state, anchors, fallback, ideology)   scripts/dtag_session.py
        ↑
DTAGEngine   (catalog, model registry, profiles, EB routing)   scripts/dtag_engine.py
        ↑                                   ↑
FastAPI  webapp/backend/dtag_web     CLI  scripts/pipeline.py (same DTAGSession)
        ↑
React/TypeScript UI  webapp/frontend
```

Survey-response anchors always come from native LSM conditional
distributions. The OpenAI model only maps questions to survey variables,
interprets the persona, bridges semantic fallback and renders the anchored
answer in prose. See [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the
design and the scientific-equivalence evidence.

---

## Quick start: direct Git install (no clone)

```bash
python3.13 -m venv .venv
source .venv/bin/activate

python -m pip install \
  "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"

export OPENAI_API_KEY="..."
dtag-web                      # http://127.0.0.1:8000
```

`dtag-web --host 0.0.0.0 --port 8080` changes the bind address. The installed
package contains the backend, the built frontend, maps, configs and the native
runtime; models are fetched on demand.

Other installed commands:

```bash
dtag --list                   # configured interactive profiles
dtag --profile gss2024_cm     # terminal respondent (same engine)
dtag-models --list            # public model catalog (* = installed)
dtag-models gss/gss_2024      # install one model
dtag-doctor                   # readiness checks
```

## Source checkout

```bash
git clone https://github.com/zeroknowledgediscovery/DTAG.git
cd DTAG
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd webapp
cp .env.example .env          # set OPENAI_API_KEY
./run.sh                      # http://localhost:8000  (UI + API on one port)
```

Development mode (API auto-reload on :8000, Vite dev server with hot reload on
:5173 proxying `/api`):

```bash
cd webapp && ./run.sh --dev
```

Rebuild the production frontend after UI changes:

```bash
cd webapp/frontend && npm ci && npm run build   # writes webapp/frontend/dist
```

The built `dist/` is committed so that direct Git installs do not need Node.

## Docker

One container, one port, models on a persistent volume (not in the image):

```bash
cd webapp
cp .env.example .env          # set OPENAI_API_KEY
docker compose up --build
# open http://localhost:8000
```

or

```bash
docker build -f webapp/Dockerfile -t dtag-web .          # from the repo root
docker run -p 8000:8000 -e OPENAI_API_KEY -v dtag-data:/data dtag-web
```

The image is based on `python:3.13-slim-trixie` because the prebuilt
`dtag_lsm` extension requires CPython 3.13 and glibc ≥ 2.38. If it does not
import, the build compiles it from `native/lsm_runtime` automatically
(`--build-arg DTAG_REBUILD_NATIVE=1` forces this). No OpenAI or cloud
credentials are baked into the image; the public model bucket is read
anonymously over HTTPS.

## Model cache management

Resolution order (shared by the CLI, `dtag-models` and the web server):

1. `DTAG_MODEL_ROOT` if set;
2. an already-populated `<repo>/models/lsm/` (developer checkouts);
3. `~/.cache/dtag/models/`.

Missing models are downloaded from the public release manifest
(`DTAG_MODEL_RELEASE`, default `v0.2.1`), SHA256-verified, safely extracted
once, validated (`source_maps/` + `trees/binary/`), then loaded **once per
server process** into a persistent `dtag_lsm.Runtime`. Every later respondent
using that model shares the resident runtime; each respondent keeps its own
survey state.

From the browser: select a profile, and the model panel shows
`not installed → Downloading → Verifying → Extracting → Loading native LSM → Ready`.
“Install model” prefetches; “Start respondent” installs automatically.

From the API:

```bash
curl -X POST localhost:8000/api/models/gss/gss_2024/install          # background job
curl localhost:8000/api/models/gss/gss_2024/status                  # poll
curl -X POST 'localhost:8000/api/models/gss/gss_2024/install?wait=true&load=false'
```

From the shell: `dtag-models gss/gss_2024`, `dtag-models --family gss`,
`dtag-models --all` (≈0.9 GB compressed, ≈6.6 GB installed).

## Environment

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | server-side only; never sent to the browser |
| `DTAG_PASSWORD` | when set, the whole app requires this shared password (login page; `Authorization: Bearer <password>` for scripts); `/api/health` stays open |
| `DTAG_SESSION_SECRET`, `DTAG_AUTH_HOURS` | login-cookie signing key (random per process if unset → restart logs everyone out) and lifetime (default 12 h) |
| `DTAG_OPENAI_MODEL` | override the configured model (default `gpt-4.1-mini`) |
| `DTAG_LLM_BACKEND=mock` | deterministic mock language layer for demos/tests (native anchors stay real; UI shows MOCK) |
| `DTAG_MODEL_ROOT` | native model cache |
| `DTAG_MODEL_RELEASE`, `DTAG_PUBLIC_BUCKET`, `DTAG_MODEL_MANIFEST_URL` | public model release |
| `DTAG_CONFIG` | DTAG config (default `configs/dtag_config.yaml`) |
| `DTAG_EURODATES` | Eurobarometer fieldwork registry (default `configs/eurodates.csv`) |
| `DTAG_HOST`, `DTAG_PORT` | bind address |
| `DTAG_WEB_DATA_DIR` | custom profiles (`profiles.json`) |
| `DTAG_ASSETS_DIR` | possible-response and embedding caches |
| `DTAG_MAX_SESSIONS`, `DTAG_SESSION_TTL_HOURS` | in-memory session store limits |
| `DTAG_MAX_LOADED_MODELS` | resident native models kept in memory (default 6, LRU) |

Run a **single worker process**: the native-model cache and sessions are
process-level (`dtag-web` does this).

## Using the workbench

1. **Describe the respondent** (left, top): optionally start from a preset
   (configured profiles from `configs/dtag_config.yaml`, or your custom ones),
   then edit **Who** (description), **Where** (country) and **When** (year, or an
   exact date for Eurobarometer). A country or year mentioned in the
   description is detected and shown ("country Kenya ← “kenya”"); the fields
   override it. US states and cities count as the United States.
2. **The survey model is chosen for you.** DTAG proposes the best native model
   from each survey family that covers the respondent and pre-selects a
   default, ranked by time fit (within a year > within three years > further),
   then by how directly the country conditions the model (categorical country
   variable > national sample > country present but contextual > coordinate
   proxy), then recency. Each option shows *when* (wave/round/fieldwork) and
   *where* (what is actually conditioned). Pick another option, or “Choose a
   specific native model…”, to override. Examples: Nigeria 2012 → Afrobarometer
   R5 (`COUNTRY_ALPHA='Nigeria'`); France 2019-05-15 → Eurobarometer ZA7575;
   India 2018 → WVS7 (`A_YEAR=2018` + coordinates); rural Alabama → GSS 2024.
3. **The chosen model is downloaded (once) and loaded automatically**; the
   option shows `download 2.4 MB → downloading → verifying → extracting →
   loading → loaded`. Start respondent waits for it if it is still loading.
4. **Start respondent.** Suggested questions appear (only questions that map
   directly onto the loaded model's survey variables; hover shows which);
   click one or type your own.
5. **Centre**: each answer has a *Model evidence* panel (selected variables,
   survey wording, full native distribution, anchor, rationale, mapping class,
   fallback and map provenance, state updates, conditioning, timings).
6. **Right**: model/map/wave/country/conditioning summary, ideology index and
   trajectory (GSS only), session timeline (`DIRECT`, `SEMANTIC / ANSWER ONLY`,
   `SEMANTIC / STATE UPDATE`, `NO MATCH`), current and initial survey state,
   JSON/CSV export.

### Question sequences

**Run sequence…** (next to *Ask*) runs many questions, in order, through the
current respondent. Upload a text file with one question per line, or paste
them (blank lines and lines starting with `#` are ignored; a first line
`question` is treated as a header, so the files in `assets/question_sets/`
work as-is; up to 500 questions). Optionally reset the respondent first;
otherwise the sequence continues from the current state.

Each question goes through the normal path (same native anchors, fallback
rules and state updates), so the survey state carries forward from one answer
to the next. Answers appear in the chat as they arrive, the ideology chart
updates live, and the **Question sequence** card shows progress, lets you
cancel after the current question, and — when the survey has an ideology
index (GSS) — reports the index at the start and end of the sequence, the net
change, the range, and the questions that moved it most (click to jump). The
full per-question record is in the session's JSON/CSV export.

API: `POST /api/sessions/{id}/sequence` with `{"text": "...one per line...",
"name": "...", "reset_first": false}` (or `{"questions": [...]}`) starts a
background run; `GET /api/sessions/{id}/sequence[?since=N]` returns progress,
new results and the ideology summary; `DELETE` cancels. While a sequence runs,
interactive questions and reset return 409.

### Two respondents side by side

The **Respondents 1 | 2** switch in the top bar adds a second respondent (the
choice is remembered in the browser). Each respondent is fully independent:
its own description (who / where / when), its own recommended or hand-picked
native model (A can be GSS 2024 while B is GSS 2018 or another survey), its
own behaviour settings and its own server session. Respondent A opens on the
`gss2024_cm` preset and B on `gss2024_wf`.

- **Left**: tabs *Respondent A* / *Respondent B* switch which setup is shown;
  *Start both respondents* starts (or restarts) both, and each tab keeps its
  own *Start* / *Reset*.
- **Centre**: the chat splits into two columns, blue for A and orange for B,
  each headed by its model, description and current ideology index. The
  composer's **Both / A only / B only** selector decides who gets the
  question; *Both* sends it to both at the same time and each answers from
  its own model and state. *Run sequence…* runs the list on the selected
  respondent(s) in parallel.
- **Right**: *Ideology · A vs B* plots both trajectories on one chart (A: solid
  line, circles; B: dashed line, squares — so color is never the only cue),
  with current / initial / change for each and the gap A − B. When the two
  use different waves, each index is measured against its own wave's poles
  (noted under the chart). Below it, tabs show each respondent's model,
  timeline, state and exports.

Switching back to one respondent hides B without ending its session.

“Save as custom profile” stores the current respondent (never in the config
file); “Advanced profile builder…” also lets you choose the semantic map.

Country conditioning (shared by CLI and web, `pipeline_localized`) uses, in
order: a variable named *country* (e.g. Afrobarometer `COUNTRY_ALPHA`,
Eurobarometer `country="FR - France"`); the Eurobarometer ISO 3166 variable
`isocntry` (`FR`, `DE-W`, …; this decodes the 2021–2023 waves whose `country`
is numeric-only); and, for older Eurobarometer waves, the variable the semantic
map labels `NATION` (`v3`/`v4`/… with values like `FRANCE`, `DEUTSCHLAND`).
The extra steps apply only when the earlier ones find nothing and accept a
value only if it is the unique match, so "Germany" in a wave split into East
and West stays contextual. All 207 Eurobarometer waves carry usable country
information.

The recommender's country/year coverage comes from `configs/model_coverage.json`,
generated from the models' own source maps by
`python scripts/build_model_coverage.py` (streams each public archive, reads
only its source maps). Afrobarometer round periods are approximate published
fieldwork years (the native models carry no date variable). Starter questions
live in `configs/suggested_questions.yaml`. At most `DTAG_MAX_LOADED_MODELS`
(default 6) models stay resident; the least recently used is released first.

## API

OpenAPI docs: `http://localhost:8000/docs`.

```text
GET    /api/health                         GET  /api/readiness[?refresh=true]
GET    /api/profiles                       GET  /api/profiles/{name}
POST   /api/profiles/validate              POST /api/profiles        DELETE /api/profiles/{name}
GET    /api/models[?family=]               GET  /api/models/{family}/{name}
GET    /api/models/{family}/{name}/status  POST /api/models/{family}/{name}/install[?load=&wait=]
GET    /api/maps                           GET  /api/polar-vectors   GET /api/geography
POST   /api/recommend                      GET  /api/countries       GET /api/sessions/{id}/suggestions
POST   /api/sessions/{id}/sequence         GET  /api/sessions/{id}/sequence[?since=N]   DELETE /api/sessions/{id}/sequence
GET    /api/eurobarometer/waves[?year=]    GET  /api/eurobarometer/resolve?date=|za=|year=
POST   /api/sessions                       GET  /api/sessions        GET /api/sessions/{id}
POST   /api/sessions/{id}/questions        POST /api/sessions/{id}/reset
DELETE /api/sessions/{id}                  GET  /api/sessions/{id}/export?format=json|csv
```

Example:

```bash
SID=$(curl -s -X POST localhost:8000/api/sessions -H 'content-type: application/json' \
  -d '{"profile":"gss2024_cm","overrides":{"resp_mode":"max","semantic_fallback":"answer_only"}}' \
  | python -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')

curl -s -X POST localhost:8000/api/sessions/$SID/questions -H 'content-type: application/json' \
  -d '{"question":"What are your thoughts about immigration?"}'

curl -s "localhost:8000/api/sessions/$SID/export?format=csv"
```

Eurobarometer by date and country:

```bash
curl -s -X POST localhost:8000/api/sessions -H 'content-type: application/json' -d '{
  "model_key": "eurobarometer/ZA7575_v1-0-0",
  "overrides": {"date": "2019-05-15", "country": "France"}}'
```

Only whitelisted, bounded override fields are accepted (persona, country,
continent, year, date, za, model_key, map_key, ideology, polar_set,
semantic_fallback, resp_mode, semantic_resp_mode, seed and numeric runtime
parameters). Model keys are validated against the catalog, map keys against
the repository map inventory, and polar-vector sets against the families they
are registered for. No paths, commands, modules or URLs are accepted.

## Scientific notes

* **WHERE** is reported exactly as applied: `categorical_country` (e.g.
  Afrobarometer `COUNTRY_ALPHA`, Eurobarometer `country="FR - France"`),
  `coordinates` (WVS `O1_LONGITUDE`/`O2_LATITUDE` snapped to model support), or
  `survey_context_only` (e.g. GSS: the country appears in the persona text but
  constrains no model variable).
* **WHEN**: GSS time selects a wave model; WVS may condition `A_YEAR`;
  Eurobarometer dates route to exactly one fieldwork interval from
  `configs/eurodates.csv` (ambiguous or uncovered dates are errors; a year alone
  never selects a wave; no interpolation between waves).
* **Ideology** is `I(s) = (d(sL,s) − d(sR,s)) / d(sL,sR)` with native
  qdistance, available only for GSS with the registered polar vectors. It is
  never derived from answer text and never reused for other survey families.
* **Semantic fallback**: `off` (no fallback), `answer_only` (grounds the answer
  but never mutates state), `update_state` (accepted bridge anchors update
  state). Each answer records which case applied.
* **Response mode** applies to the native anchor: `max` takes the modal
  response, `draw` samples the native distribution with seed `seed + question`.
* Eurobarometer maps built by semantic-union fallback keep their provenance
  (`map_provenance`, `fallback_*`) on every anchor and in exports.
* Exports include DTAG version and Git commit, model key/release/SHA256, map
  provenance summary, profile, persona text, requested/resolved geography and
  time, seed, response mode, fallback mode, LLM model, initial state, every
  question with selected variables, full distributions, anchors, state updates,
  ideology and timings, plus the CLI-schema records.

## Access control

Set `DTAG_PASSWORD` to protect a shared or internet-facing server. Browsers get
a sign-in page and an HttpOnly, SameSite=Lax cookie (Secure over HTTPS) signed
with HMAC-SHA256 and bound to the password (changing the password signs
everyone out). Failed logins are throttled per client (10 per 15 min). All
pages and API routes are protected except `/api/health` (for load-balancer
probes). Always serve it over HTTPS (e.g. Caddy or a cloud load balancer) so
the password is never sent in clear text. With `DTAG_PASSWORD` unset (the
default) the app is open, which is intended for local use only.

```bash
curl -H "Authorization: Bearer $DTAG_PASSWORD" https://<host>/api/profiles
```

## Tests

```bash
pip install pytest httpx
cd webapp/tests
pytest -q                         # all tiers; native tier downloads gss/gss_2024 if needed
DTAG_TEST_OFFLINE=1 pytest -q     # skip the native/network tier
```

The fast tier uses a deterministic fake native backend and a mock language
layer. The native tier runs against a real model: model-load-once/shared
runtime with independent respondent state, runtime persistence and latency,
concurrent sessions on one model, fallback semantics, CLI and API end-to-end,
and country conditioning for any installed Afrobarometer/WVS/Eurobarometer
models. No test needs `OPENAI_API_KEY`.

Development benchmark in this environment (GSS 2024, 813 features): preload
≈6.6 s once; single-variable prediction ≈0.4 ms; qdistance ≈0.07 s; two pole
distances ≈0.1 s. These are reference numbers, not guarantees.
