# DTAG — Digital Twin Anchored Generation

ZeD Lab, University of Kentucky · contact: ishanu_ch@uky.edu

DTAG builds survey-grounded digital twins of respondents. Every answer is anchored to the
conditional response distributions of native Large Science Models trained on the GSS, the World
Values Survey, Afrobarometer and Eurobarometer: 252 models, each with a semantic map.

This README is the platform manual. It covers what DTAG is for and how it works, describes every part
of the web workbench, and says where each piece of information comes from: the models, maps, poles,
registries and the language model. It also lists exactly which surveys, years and countries are covered.

| If you want to… | Read |
|---|---|
| get the web app running in five minutes | **[QUICKSTART.md](QUICKSTART.md)** |
| understand and use the platform | this manual |
| call the HTTP API or work on the web app | [webapp/README.md](webapp/README.md), [webapp/HANDOFF.md](webapp/HANDOFF.md) |
| work on the code, maps, poles or models | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| see the question-optimization research | [docs/QUESTION_OPTIMIZATION.md](docs/QUESTION_OPTIMIZATION.md), [optimizer/README.md](optimizer/README.md) |

---

## Contents

1. [What DTAG is](#1-what-dtag-is)
2. [What DTAG is supposed to do (and not do)](#2-what-dtag-is-supposed-to-do-and-not-do)
3. [Core concepts](#3-core-concepts)
4. [Architecture](#4-architecture)
5. [Installing and running the web app](#5-installing-and-running-the-web-app)
6. [Native models: where they are and how they are pulled in](#6-native-models-where-they-are-and-how-they-are-pulled-in)
7. [Other information DTAG uses](#7-other-information-dtag-uses)
8. [Survey coverage](#8-survey-coverage)
9. [What happens when you ask a question](#9-what-happens-when-you-ask-a-question)
10. [The web workbench, feature by feature](#10-the-web-workbench-feature-by-feature)
11. [Settings reference](#11-settings-reference)
12. [Outputs, logs and reproducibility](#12-outputs-logs-and-reproducibility)
13. [HTTP API summary](#13-http-api-summary)
14. [Environment variables](#14-environment-variables)
15. [Deployment and access control](#15-deployment-and-access-control)
16. [Testing and readiness checks](#16-testing-and-readiness-checks)
17. [Troubleshooting](#17-troubleshooting)
18. [Assumptions, limitations and interpretation](#18-assumptions-limitations-and-interpretation)
19. [Credits and data sources](#19-credits-and-data-sources)

---

## 1. What DTAG is

DTAG builds a **digital twin of a survey respondent** and lets you question it in natural language.

You describe a person (*who*, *where*, *when*). DTAG picks the large survey whose wave, place and time
fit that description: the General Social Survey, the World Values Survey, Afrobarometer or
Eurobarometer. It then loads a **native Large Science Model (LSM)** trained on that survey and
sets up a *survey state* for the twin: an explicit list of survey items and their answers that
encodes the persona.

When you ask the twin a question, DTAG:

1. matches the question to the survey item(s) that measure it;
2. asks the LSM for the **conditional distribution** of answers to those items, given everything
   already in the twin's state;
3. takes the twin's answer from that distribution (draws it, or takes the most likely answer);
4. writes the answer into the state, so that later answers are conditioned on it;
5. has a language model phrase the anchored answer in the twin's voice.

Every answer is therefore **anchored** to what real respondents with this profile and these earlier
answers said in the survey. The language model never invents the substance of an answer. It only
reads, routes and phrases.

The web workbench lets you watch that process. It shows the evidence behind every answer, the
whole *decision landscape* of predicted answers, and how one answer reshapes the rest. For GSS
respondents it also tracks an ideology index. You can steer the twin with optimizer-suggested
questions, and record any interaction as an experiment that can be rerun many times with statistics.

## 2. What DTAG is supposed to do (and not do)

**Intended uses**

- *Survey-grounded simulation.* Get answers that a respondent with a given profile, place and time
  would plausibly give, together with the full predicted distribution behind each answer.
- *Stateful questioning.* Study how answers depend on what has already been answered: question-order
  and context effects inside the model's learned dependency structure.
- *Opinion-drift experiments.* Ask a sequence of questions, push the twin toward a pole, or replay a
  recorded recipe N times. Then measure how the predicted state, the ideology index (GSS) and the
  decision landscape move, with confidence intervals.
- *Question design.* Find which survey items are most informative or most "moving" at a given state
  (one-step optimizer), and check whether a natural-language question actually reaches the item
  you intended.
- *Cross-survey comparison.* Run two respondents side by side, on the same or different surveys,
  waves or countries.
- *Transparent evidence.* Every answer exposes the selected variables, the survey wording, the
  native distribution, the anchor, the mapping rationale, the state updates and the timings.

**What DTAG is not**

- It is not a model of a real individual, and not a deterministic forecast of anyone's choices.
- It is not a causal simulator. Conditional predictions are associations in survey data, so
  "answering X moves Y" means the model's prediction for Y changes once X is known. It does not mean
  that persuading someone of X would change their view on Y.
- It is not a free-form chatbot. If no survey item matches a question, DTAG says so (or uses the
  clearly marked semantic fallback) rather than making something up.
- It does not interpolate between survey waves. Time selects a discrete wave.

## 3. Core concepts

| Concept | Meaning |
|---|---|
| **Native LSM** | A trained model of one survey wave (or pooled survey). For every survey item it holds a decision tree that predicts that item's answer distribution from the other items. DTAG runs it through the bundled C++ runtime `dtag_lsm` (pybind11). |
| **Survey state** | An ordered map `item → answer` for the twin. It is set from the persona and the conditioning (place/time), then grown by every answer. It is capped at `state_keep` items; when full, the oldest entries are evicted. |
| **Conditional distribution** | `P(answer of item v ∣ state)` from the LSM. Every answer the twin gives is drawn from, or is the mode of, this distribution. |
| **Anchor** | The concrete survey answer chosen for an item, with its probability and full distribution. The prose answer is written to agree with the anchors. |
| **Semantic map** | A CSV per model linking each native variable to its survey question text and answer labels. It is used to match questions to items and to show wording. |
| **Persona interpretation** | The language model turns the persona description into item assignments, choosing only from answers the model allows (e.g. `sex=female`, `age=22`, `polviews=extremely liberal`). |
| **Conditioning** | Deterministic constraints from *where* and *when*: a country variable, an ISO code, coordinates, or a survey year. These come from survey variables, not from the language model. |
| **Ideology index (GSS)** | `I(s) = (d(L,s) − d(R,s)) / d(L,R)`. Here `d` is the LSM *qdistance* (Jensen–Shannon divergence between predicted distributions, averaged over the model's trees), and `L`/`R` are the left and right pole states for that GSS wave. The index rises toward R. |
| **Decision landscape** | The predicted answer to every askable item at the current state: how settled each item is, how it leans, and which items moved after the last answer. |
| **Recipe** | The recorded list of actions on a respondent (questions, pushes, sequences, resets). It can be replayed as a new experiment. |

## 4. Architecture

```text
React / TypeScript UI                      webapp/frontend  (built dist/ is committed)
        ↓ HTTP (JSON)
FastAPI backend                            webapp/backend/dtag_web
  sessions, sequences, experiments, exports, auth
        ↓
DTAGEngine                                 scripts/dtag_engine.py
  catalog, model registry (LRU), profiles, recommender, Eurobarometer routing,
  push suggestions, landscape jobs
        ↓
DTAGSession  (one respondent)              scripts/dtag_session.py
  persona → state, question mapping, anchors, semantic fallback, ideology
        ↓                         ↘
dtag_core (maps, LLM steps,         optimizer/  (one-step geometry, session_push,
  distributions, geography)                       landscape, topics)
        ↓
native LSM runtime (persistent)            scripts/model_backend.py → native/lsm_runtime (dtag_lsm)
```

- **One model is loaded once per server process** and shared by every respondent that uses it. Each
  respondent keeps its own state. At most `DTAG_MAX_LOADED_MODELS` models (default 6) stay
  resident; the least recently used is released first.
- The LSM decides *what* the twin answers. The language model (OpenAI, default `gpt-4.1-mini`) only:
  maps questions to items, interprets the persona, selects semantic-fallback bridge items, writes
  neutral wording for suggested items, and turns anchors into prose.
- `DTAG_LLM_BACKEND=mock` swaps in a deterministic mock language layer for demos and tests. Native
  anchors, state and ideology are still computed by the real models, and the UI shows **MOCK**.

## 5. Installing and running the web app

### 5.1 Requirements

- Python **3.13** on **x86-64 Linux** to use the bundled prebuilt native extension. Other platforms
  need to build it once with `bash scripts/build_native_bindings.sh` (requires a C++17 compiler and
  pybind11).
- Internet access to the public model store (models are downloaded on demand).
- An OpenAI API key for real use. Without one, run with `DTAG_LLM_BACKEND=mock`.

### 5.2 Install without cloning

```bash
python3.13 -m venv dtag-env && source dtag-env/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"   # or @dev for new features
export OPENAI_API_KEY="sk-..."
dtag-web                                  # open http://127.0.0.1:8000
```

`pip install` provides three commands:

| Command | What it does |
|---|---|
| `dtag-web [--host H] [--port P]` | Starts the web workbench and API on one port (default `127.0.0.1:8000`; OpenAPI docs at `/docs`). |
| `dtag-models …` | Lists, downloads and verifies native models (see §6). |
| `dtag-doctor` | Runs the readiness and clean-surface checks (see §16). |

To update, stop the server and run
`pip install --upgrade --force-reinstall "git+https://github.com/zeroknowledgediscovery/DTAG.git@dev"`.

### 5.3 Run from a source checkout

```bash
git clone https://github.com/zeroknowledgediscovery/DTAG.git && cd DTAG
git checkout dev                           # development branch
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd webapp
cp .env.example .env                       # put OPENAI_API_KEY (and optional settings) here
./run.sh                                   # production mode: UI + API on http://localhost:8000
./run.sh --dev                             # API with auto-reload on :8000 + Vite dev server on :5173
```

`run.sh` loads `webapp/.env` and checks that the Python dependencies and the native extension import.
It refuses to start without `OPENAI_API_KEY` unless `DTAG_LLM_BACKEND=mock` is set.

After changing the UI, rebuild it with `cd webapp/frontend && npm ci && npm run build`. The build
writes `webapp/frontend/dist`, which is committed so that Git installs do not need Node.

Equivalent manual launch:

```bash
PYTHONPATH=webapp/backend:scripts python -m dtag_web --host 127.0.0.1 --port 8000
```

Always run **a single worker process**. The model cache, sessions and background jobs live in
process memory.

### 5.4 Docker

```bash
cd webapp && cp .env.example .env && docker compose up --build      # http://localhost:8000
# or, from the repository root:
docker build -f webapp/Dockerfile -t dtag-web .
docker run -p 8000:8000 -e OPENAI_API_KEY -v dtag-data:/data dtag-web
```

Models go on the persistent `/data` volume, not into the image. The image is based on
`python:3.13-slim-trixie`. If the prebuilt extension does not import, the native runtime is compiled
during the build (`--build-arg DTAG_REBUILD_NATIVE=1` forces this).

### 5.5 First session in five steps

1. **Describe the respondent** (left column). Start from a preset or type *Who*
   (e.g. `35 year old primary school teacher in Kenya, listens to the radio`). Add *Where* (country)
   and *When* (a year, or an exact date for Eurobarometer) if you like. A country or year mentioned in
   the description is detected automatically; the explicit fields override it.
2. **Check the survey model.** DTAG proposes the best model from each survey family that covers the
   respondent and marks a **DEFAULT** (see §10.2). You can pick another, or choose any model by hand.
3. **Start respondent.** The model is downloaded (once), verified, extracted and loaded, then the
   persona is interpreted into an initial survey state.
4. **Ask questions**, either typed or by clicking a suggested question. Open *Model evidence* under an
   answer to see the distribution and anchors behind it.
5. **Watch and export.** Use the landscape (left), ideology and next-question suggestions (right),
   and *Session → Export* for the full log.

## 6. Native models: where they are and how they are pulled in

### 6.1 The public model store

The native models are **not in Git** (≈0.94 GB compressed, ≈6.6 GB installed). They are published
as one compressed archive per model in a public Google Cloud Storage bucket. The bucket is read
anonymously over HTTPS, so no cloud credentials are needed.

| Item | Value |
|---|---|
| Bucket | `git-zeroknowledgediscovery-dtag` (override: `DTAG_PUBLIC_BUCKET`) |
| Release | `v0.2.1` (override: `DTAG_MODEL_RELEASE`) |
| Manifest | `https://storage.googleapis.com/git-zeroknowledgediscovery-dtag/models/v0.2.1/manifest.json` (override the whole URL with `DTAG_MODEL_MANIFEST_URL`) |
| Archive per model | `models/<release>/<family>/<name>.tar.zst`, with a SHA256 checksum and size in the manifest |
| Model key | `<family>/<name>`, e.g. `gss/gss_2024`, `afrobarometer/r9`, `wvs/wvs7_pooled`, `eurobarometer/ZA7575_v1-0-0` |

Compressed sizes by family in release v0.2.1:

| Family | Models | Compressed |
|---|---:|---:|
| GSS | 35 | 47 MB |
| WVS7 | 1 | 61 MB |
| Afrobarometer | 9 | 225 MB |
| Eurobarometer | 207 | 610 MB |
| **Total** | **252** | **≈ 943 MB** |

### 6.2 Where models are installed

`scripts/dtag_paths.py::model_root()` decides the local model root. The downloader, the web server
and the optimizer all use it, so they always agree. It checks, in order:

1. `$DTAG_MODEL_ROOT`, if set;
2. `<repo>/models/lsm/`, if it already contains installed models (developer checkouts);
3. `~/.cache/dtag/models/` (the default for fresh installs).

Layout under the root:

```text
<model_root>/
  gss/gss_1972 … gss/gss_2024
  wvs/wvs7_pooled
  afrobarometer/r1 … afrobarometer/r9
  eurobarometer/ZA0078_v1-0-1 … eurobarometer/ZA8843_v1-0-0
```

Each model directory must contain `source_maps/` (the model's own variable/answer dictionaries) and
`trees/binary/` (the trained trees). A directory is treated as installed only if both are present.
Configured paths of the form `models/lsm/...` (e.g. in `configs/dtag_config.yaml`) are redirected to
the model root automatically.

### 6.3 How a model is pulled in

`scripts/fetch_models.py::fetch_one` installs a model in these steps:

```text
manifest lookup → download .tar.zst (streamed) → SHA256 verify → safe extract
 (no absolute paths, no "..", no links outside) → validate source_maps/ + trees/binary/
 → move into <model_root>/<family>/<name>
```

The web server then loads the model **once** into a persistent `dtag_lsm.Runtime`, which keeps the
usable trees and dictionaries in memory. Every later respondent on that model reuses it.

There are three ways to trigger a download:

- **Automatically, from the browser.** Choosing a respondent selects a model. The model option shows
  `download 2.4 MB → downloading → verifying → extracting → loading → loaded`. *Start respondent*
  waits for this if needed.
- **From the shell:**
  ```bash
  dtag-models --list                 # catalog (* = installed)
  dtag-models gss/gss_2024           # one model
  dtag-models --family afrobarometer # one family
  dtag-models --all                  # all 252 models
  ```
- **From the API:**
  ```bash
  curl -X POST localhost:8000/api/models/gss/gss_2024/install          # background job
  curl localhost:8000/api/models/gss/gss_2024/status                   # progress
  curl -X POST 'localhost:8000/api/models/gss/gss_2024/install?wait=true&load=false'
  ```

Model keys are validated against the pattern `^(gss|afrobarometer|wvs|eurobarometer)/[A-Za-z0-9._-]+$`
and against the catalog. The API never accepts paths or URLs.

### 6.4 Pre-populating an offline machine

Run `DTAG_MODEL_ROOT=/shared/dtag-models dtag-models --all` on a connected machine. Then copy the
directory and set `DTAG_MODEL_ROOT=/shared/dtag-models` on the offline one. Installed models are never
downloaded again.

## 7. Other information DTAG uses

Apart from the models, DTAG reads only versioned files from the repository, plus two local caches.
Nothing else is fetched at run time except model archives and language-model calls.

| Information | Location | Used for |
|---|---|---|
| **Semantic maps** | `maps/gss/gss_YYYY_map.csv` (35), `maps/afromap/afrobarometer_rN_map.csv` (9), `maps/wvs7_variable_question_map.csv` (1), `maps/eurobarometer/ZAxxxx_map.csv` (207) | Item wording and answer labels. They are used to match questions to items, to show evidence and to give the LLM context. Every model feature has a row; undocumented variables keep their native name. |
| **Map provenance (Eurobarometer)** | columns `map_provenance`, `fallback_*` in the EB maps | Waves without usable GESIS documentation use a *semantic-union fallback* map built from documented waves (`UNION_CONSENSUS`, `UNION_SUPPORT_MATCH`, `UNION_CONTEXT_MATCH`, `UNRESOLVED_NATIVE`). The provenance appears on every anchor and in exports. |
| **Configuration and profiles** | `configs/dtag_config.yaml` (`DTAG_CONFIG`) | Default run settings (§11) and named presets (`interactive_profiles`): `gss2018_wf/cm`, `gss2022_wf/cm`, `gss2024_wf/cm`, `wvs7_india_2017`, `afrobarometer_r5_nigeria`, `afrobarometer_r5_ghana`. Resolution order: defaults < profile < request overrides. |
| **Custom profiles** | `$DTAG_WEB_DATA_DIR/profiles.json` (`webapp/data` with `run.sh`) | Respondents you save from the UI. They are never written into the config file. |
| **Model coverage** | `configs/model_coverage.json` | The recommender's knowledge of which countries and years each model covers, and which variable conditions the country. It is generated from the models' source maps by `scripts/build_model_coverage.py`. |
| **Afrobarometer round periods** | `scripts/dtag_recommend.py` (`AFRO_ROUND_YEARS`) | Approximate published fieldwork years per round. The models carry no date variable. |
| **Eurobarometer fieldwork registry** | `configs/eurodates.csv` (`DTAG_EURODATES`) | Maps a calendar date to exactly one fieldwork wave (`scripts/eurobarometer_dates.py`). |
| **Ideology poles (GSS)** | `assets/polar_vectors/polar_vectors.csv` (canonical), `assets/polar_vectors/gss/gss_YYYY_polar_vectors.csv` (per wave), `gss_pole_corrections.csv` | The L and R reference answers that define the ideology index. They are resolved per wave so that only items with both pole answers present in that wave are used. |
| **Starter questions** | `configs/suggested_questions.yaml` | Clickable example questions. Only those that map directly onto the loaded model are shown. |
| **Question sets** | `assets/question_sets/` (`master`, `divergence`, `optimized`, `polarization`, `depolarization`, `demo`, …) | Ready-made inputs for *Run sequence…* (one question per line, or CSV with a `question` column). |
| **Topic keywords** | `optimizer/topics.py` | Groups items into topic arcs for the landscape (with *Background* and *Other* buckets). |
| **Possible-response cache** | `$DTAG_ASSETS_DIR` (default `~/.cache/dtag/assets`) | The allowed answers per item, read from the model once and cached per model signature. |
| **Embedding cache** | same directory | Embeddings of map rows (`text-embedding-3-small`), used only for the semantic fallback. Computed once per map. |
| **Language model** | OpenAI API (`OPENAI_API_KEY`, model `gpt-4.1-mini`, override `DTAG_OPENAI_MODEL`) | Persona interpretation, item selection, semantic bridge selection, neutral question wording for suggestions, answer prose. The key stays on the server. |

**What the language model sees.** It sees the persona text, the question, the candidate items with
their map wording and allowed answers, and the anchored answers it must phrase. It never sees model
files, and it does not choose the answers: it must stay consistent with the anchors drawn from the LSM.

## 8. Survey coverage

Release v0.2.1 contains **252 native models and 252 semantic maps**, with complete model–map feature
overlap (verified by `scripts/audit_native_maps.py --deep`).

### 8.1 General Social Survey (GSS), United States — 35 models

One model per wave. Number of model features in parentheses:

1972 (197) · 1973 (317) · 1974 (329) · 1975 (386) · 1976 (391) · 1977 (428) · 1978 (441) · 1980 (461) ·
1982 (507) · 1983 (493) · 1984 (618) · 1985 (631) · 1986 (526) · 1987 (641) · 1988 (692) · 1989 (684) ·
1990 (771) · 1991 (781) · 1993 (676) · 1994 (915) · 1996 (1089) · 1998 (908) · 2000 (1128) ·
2002 (1038) · 2004 (1180) · 2006 (1277) · 2008 (832) · 2010 (817) · 2012 (805) · 2014 (863) ·
2016 (913) · 2018 (1034) · 2021 (740) · 2022 (880) · 2024 (811)

- *When* selects the wave (nearest wave to the requested year).
- *Where* is context only. The GSS is a national US sample, so a country, state or city enters
  the persona text but constrains no model variable.
- The **ideology index is available for all 35 waves**, using wave-specific poles. GSS is the only
  family with an ideology index.

### 8.2 World Values Survey wave 7 (WVS7) — 1 pooled model

`wvs/wvs7_pooled` has 375 features and covers fieldwork years 2017–2023 across the WVS7 countries.

- *When*: the year is conditioned through `A_YEAR` (2017–2023) when the model supports it.
- *Where*: the country is conditioned through coordinates (`O1_LONGITUDE`, `O2_LATITUDE`), snapped to
  the model's support.

### 8.3 Afrobarometer — 9 models (rounds R1–R9)

| Round | Approx. fieldwork | Features | Countries |
|---|---|---:|---:|
| R1 | 1999–2001 | 142 | 12 |
| R2 | 2002–2004 | 323 | 16 |
| R3 | 2005–2006 | 294 | 18 |
| R4 | 2008–2009 | 284 | 20 |
| R5 | 2011–2013 | 322 | 34 |
| R6 | 2014–2015 | 331 | 36 |
| R7 | 2016–2018 | 337 | 34 |
| R8 | 2019–2021 | 397 | 34 |
| R9 | 2021–2023 | 387 | 39 |

Countries covered across rounds include Algeria, Angola, Benin, Botswana, Burkina Faso, Burundi,
Cabo Verde, Cameroon, Congo-Brazzaville, Côte d'Ivoire, Egypt, Eswatini, Ethiopia, Gabon, Gambia,
Ghana, Guinea, Kenya, Lesotho, Liberia, Madagascar, Malawi, Mali, Mauritania, Mauritius, Morocco,
Mozambique, Namibia, Niger, Nigeria, São Tomé and Príncipe, Senegal, Seychelles, Sierra Leone,
South Africa, Sudan, Tanzania, Togo, Tunisia, Uganda, Zambia and Zimbabwe. The exact list for each
round is in `configs/model_coverage.json`.

- *When*: the round is chosen from the approximate fieldwork period above.
- *Where*: the country is conditioned directly through the categorical country variable
  (e.g. `COUNTRY_ALPHA='Nigeria'`).

### 8.4 Eurobarometer — 207 models (GESIS ZA studies)

These run from `ZA0078` (1962) to `ZA8843` and cover Standard, Special and Flash Eurobarometer
waves. Features per model range from 41 to 2,083 (mean ≈ 488).

- **192 waves** have fieldwork dates in `configs/eurodates.csv`, from 31 January 1962 to February 2021.
  By decade: 1960s 1, 1970s 16, 1980s 23, 1990s 46, 2000s 52, 2010s 53, 2020s 1.
- **15 newer waves** (`ZA7846–7848`, `ZA7886–7888`, `ZA7901–7902`, `ZA7952–7954`, `ZA8778–8779`,
  `ZA8841`, `ZA8843`) have no registered fieldwork date. Select them explicitly by ZA number.
- *When*: an exact **date** routes to the one fieldwork interval that contains it. Ambiguous or
  uncovered dates are errors. A year alone never selects a wave, because a year usually has several
  waves. There is no interpolation between waves.
- *Where*: every one of the 207 waves carries usable country information, applied in this order:
  1. a categorical `country` variable (e.g. `"FR - France"`);
  2. the ISO 3166 variable `isocntry` (`FR`, `DE-W`, …), which decodes the 2021–2023 waves whose
     `country` is numeric only;
  3. in older waves, the map-labelled `NATION` variable (values like `FRANCE`, `DEUTSCHLAND`).

  A value is accepted only if it is a unique match. For example, "Germany" in a wave split into
  East and West stays contextual.

### 8.5 How the model is chosen

`scripts/dtag_recommend.py` proposes the best model from every family that covers the respondent.
It ranks them by:

1. **time fit** (within a year > within three years > further);
2. **how directly the country conditions the model** (categorical country variable > national sample >
   country present but contextual > coordinate proxy);
3. **recency**.

Examples: Nigeria 2012 → Afrobarometer R5 · France 2019-05-15 → Eurobarometer ZA7575 ·
India 2018 → WVS7 (`A_YEAR=2018` + coordinates) · rural Alabama → GSS 2024. US states and cities
count as the United States.

## 9. What happens when you ask a question

### 9.1 Starting a respondent

1. The persona text is extended with any region, country and year context.
2. A lexical prefilter ranks the model's items by overlap with the persona and offers up to
   `assign_prefilter` (500) of them, with their allowed answers, to the language model.
3. The language model proposes up to `max_assign` (50) item assignments with a rationale. Assignments
   to items that are not in the model, or to answers the model does not allow, are dropped (and
   listed as dropped).
4. **Forced assignments** from geography and time (`scripts/pipeline_localized.py`) are added and
   take precedence.
5. The result is the initial survey state. For GSS, the initial ideology index (step 0) is computed.

### 9.2 Answering a question

1. **Map.** A lexical prefilter over the semantic map keeps up to `prefilter` (200) candidates
   scoring at least `min_map_score`. The language model then selects up to `k` (50) items that the
   question actually asks about. This step depends only on the question and the map, not on the state.
2. **Predict.** The LSM computes `P(answer ∣ state)` for each selected item.
3. **Anchor.** With `resp_mode: draw` (default), an answer is sampled with seed `seed + question
   index`. With `max`, the most likely answer is taken.
4. **Update state.** The anchors are written into the state (moved to the most recent position).
   The oldest entries are evicted beyond `state_keep` (500).
5. **Ideology (GSS).** The index is recomputed from the new state.
6. **Phrase.** The language model writes the twin's answer from the persona and the anchors.

If no item matches (no lexical candidate, or the language model finds no relevant item), the
**semantic fallback** runs, depending on `semantic_fallback`:

- `off`: the answer is marked **NO MATCH**.
- `answer_only`: embeddings (`semantic_prefilter`, 80 candidates) and the language model select up to
  `semantic_k` (6) *bridge* items with confidence ≥ `semantic_min_confidence` (0.35). These are
  predicted with `semantic_resp_mode` (`max`) and ground the answer, but **do not change the state**.
- `update_state` (**default**): as above, but the accepted bridge anchors **are written into the
  state**.

The session timeline tags every answer: `DIRECT`, `SEMANTIC / ANSWER ONLY`,
`SEMANTIC / STATE UPDATE` or `NO MATCH`.

## 10. The web workbench, feature by feature

### 10.1 Layout

- **Top bar**: DTAG / About (credits, version, commit), **Respondents 1 | 2**, theme toggle
  (light/dark), and **reset layout** (shown once a column has been resized).
- **Left column**: the respondent card (setup, which collapses once started) and the
  **decision landscape**.
- **Centre**: the chat stage. Answers are shown first, with metadata and *Model evidence* below.
  The composer has *Ask*, *Run sequence…* and (with two respondents) a *Both / A only / B only* target.
- **Right column**: the ideology chart (GSS), two **next-question** suggestions, then tabs for
  **Auto-push** (GSS), **Experiment** and **Session** (model details, the **Export ▾** menu, the
  timeline, and the current and initial state tables). The last tab you used is remembered.

### 10.2 Describing the respondent

- **Presets**: configured profiles plus your own saved custom profiles.
- **Who / Where / When**. Detected country or year from the description is shown with its source
  (e.g. country Kenya ← "kenya").
- **Model choice**: the default recommendation, other families' options (each shows *when* and
  *where* it conditions), or "Choose a specific native model…".
- **Behaviour settings**: response mode, semantic fallback, seed and others (§11).
- **Save as custom profile**; **Advanced profile builder…** also lets you choose the semantic map.

### 10.3 Asking and evidence

Type a question, or click a starter question or suggestion chip. Each answer's **Model evidence**
shows the selected variables, the survey wording, the full native distribution, the anchor and its
probability, the selection rationale, the mapping class, fallback and map provenance, state updates,
the conditioning applied, and timings.

### 10.4 Question sequences

**Run sequence…** runs up to 500 questions in order through the current respondent. You can upload or
paste a file with one question per line, or a CSV with a `question` column. Blank lines and lines
starting with `#` are ignored. You can reset the respondent first. The run shows progress, can be
cancelled, and reports the ideology at the start and end, the range, and the questions that moved it
most.

### 10.5 Next-question suggestions and push modes

After every answer, `optimizer/session_push.py` scores every unanswered opinion item at the current
state. Administrative, demographic and factual-behaviour items are excluded, and so are pole-defining
items unless you allow them.

- **With ideology (GSS):** two suggestions, one moving the index **up** (toward R) and one **down**
  (toward L). With `draw`, the score is the expected change `μ = Σ P(a) Δ(a)`. With `max`, it is the
  change from the modal answer (exact).
- **Without ideology (WVS, Afrobarometer, Eurobarometer):** suggestions are based on the landscape:
  **open** questions (items whose predicted answer is least settled) and **connected** questions
  (items whose answer would move the most other predictions).

The language model writes neutral wording for the suggested item. **Ask** has three modes
(**realistic** is the default):

| Mode | What happens |
|---|---|
| **realistic** | The suggested question goes through the normal mapping, like a typed question. It may reach extra items or miss the target, so the realized change can differ from the prediction. |
| **validated** | The top 5 candidates per direction are dry-run through the mapping. Questions that miss their item are dropped, and the rest are ranked by the exact change over all items they map to. The answer uses that checked mapping. |
| **push** (`direct` in the API) | The answer goes through exactly the suggested item, skipping the mapping. This is the most idealized mode. |

**Auto-push** (`Push ↑/↓ N steps`) repeats the suggestion in one direction, re-scoring at each step,
and stops early if nothing moves the index further. Chat entries are tagged **PUSH ↑/↓**, with
predicted vs realized change in the tooltip.

These are information-conditioning effects in a fixed survey model, not persuasion of people.

### 10.6 Decision landscape

This view is available for **all** surveys. Two views are offered (the toggle is remembered):

- **Doughnut.** One wedge per unanswered item, grouped into topic arcs. Wedge length shows how
  settled the predicted answer is (1 − normalized entropy). On GSS, colour shows the lean (blue = L,
  red = R). Answered items are beads on the inner ring. Wedges whose prediction moved after the last
  answer (Jensen–Shannon > 1e-4 bits) pulse with a spike sized to the shift, and the top movers are
  listed.
- **Map (terrain).** Items sit on a fixed 2D map with topic regions; items whose trees depend on each
  other are pulled together (force-directed layout, cached per model). Height shows indecision, so
  settled opinions are valleys. Answered items are pins. An expanding ring marks moved predictions.

The landscape is **live and progressive**. When an answer lands, every prediction that could change
(known from the model's dependency graph) starts shimmering. Only those items are recomputed, most
affected first and in small batches, and each batch is published as it finishes. The final view is
exact. Dense models (WVS, Afrobarometer, Eurobarometer) are computed in the background, so questions
are never blocked.

### 10.7 Experiments: record, rerun ×N, statistics

Everything you do to a respondent is recorded as a **recipe** (*Experiment* tab): typed questions,
pushes (direction and mode), auto-pushes, sequences and suggested questions. Pushes and suggestions
are recorded as *intent*. A reset starts a new recipe.

**Rerun ×N** replays the recipe N times as a background job:

- Each run uses a fresh respondent from the same profile, so the persona interpretation can vary.
- Each run gets its own seed (`base_seed + run`).
- Pushes and suggestions are re-chosen at that run's own state, and every question actually asked
  is logged.

The panel shows the mean ideology after each action, with a 95% bootstrap CI band and each run as a
faint line. It also shows the net change with its CI, the push hit rate, and which questions each
action asked across runs. Results are written to a folder (§12.2). A saved `recipe.json` can also be
run through the API (`POST /api/experiments/run`).

### 10.8 Two respondents

**Respondents 2** adds a second, fully independent respondent (own description, model, settings and
session; it may be on a different survey). Questions go to *Both*, *A only* or *B only*. The right
column overlays both ideology trajectories (A solid with circles, B dashed with squares) and shows the
gap A − B. The two-respondent ZIP log adds an aligned comparison.

### 10.9 Figures, layout and theme

- **Save figures**: hover any chart (ideology, doughnut, map, experiment band) and click its download
  button to save it as **SVG**, **PNG** (4×) or **PDF**. The map is a canvas, so it is embedded in the
  PDF as a 4× image. Theme colours are inlined.
- **Resizable columns**: drag a border; double-click it, or use *reset layout*, to restore the
  defaults. The chat wraps and never gets narrower than 360 px. Widths are remembered separately for
  one and two respondents. Below 1100 px the columns stack.
- **Theme**: light or dark, following the system until you choose.

The browser remembers: `dtag.theme`, `dtag.landscapeView`, `dtag.layout.1|2`, `dtag.rightTab` and
`dtag.respondents`.

## 11. Settings reference

These defaults come from `configs/dtag_config.yaml → defaults.run`. A profile can override them, and
so can a request (the UI behaviour panel, or `overrides` in the API).

| Setting | Default | Meaning |
|---|---|---|
| `resp_mode` | `draw` | `draw` samples the native distribution (seed `seed + question`); `max` takes the modal answer. |
| `semantic_fallback` | `update_state` | `off`, `answer_only` or `update_state` (§9.2). |
| `semantic_resp_mode` | `max` | Response mode for fallback bridge items. |
| `semantic_k`, `semantic_prefilter`, `semantic_min_confidence` | 6, 80, 0.35 | Fallback bridge selection. |
| `semantic_embedding_model` | `text-embedding-3-small` | Embeddings for the fallback. |
| `k`, `prefilter`, `min_map_score` | 50, 200, 1.0 | Direct mapping: maximum items, lexical candidates, minimum lexical score. |
| `max_assign`, `assign_prefilter` | 50, 500 | Persona interpretation. |
| `state_keep` | 500 | Maximum state size (oldest entries evicted). |
| `seed` | profile / 1000 base | Random seed for draws. |
| `openai_model` | `gpt-4.1-mini` | Language model (env override `DTAG_OPENAI_MODEL`). |
| `ideology`, `polar_set` | on for GSS | Ideology tracking and the pole set. |

The API accepts only whitelisted, bounded override fields (persona, country, continent, year, date,
za, model_key, map_key, ideology, polar_set, semantic_fallback, resp_mode, semantic_resp_mode, seed and
numeric runtime parameters). It never accepts paths, commands, modules or URLs.

## 12. Outputs, logs and reproducibility

### 12.1 Session exports

From *Session → Export ▾*:

- **Full log (ZIP)**, containing: `report.md`, `questions.csv`/`.jsonl`, `ideology_trajectory.csv` and
  `ideology.svg`, `state_changes.csv`, `persona.txt`, `persona_initialization.json`,
  `initial_state.csv`/`final_state.csv`, `settings.json`, `poles.csv`, `sequence.json`, `session.json`,
  and `manifest.json` (DTAG version and commit, model checksum, file checksums).
- **JSON** and **CSV** of the session.

The two-respondent ZIP adds `comparison.csv`/`.svg`.

### 12.2 Experiment folders

Experiments are saved to `<repo>/experiments/<name>_<timestamp>/` (or `$DTAG_EXPERIMENTS_DIR`).
This folder is ignored by Git.

```text
recipe.json  manifest.json  report.md
runs/run_NN/  trace.jsonl  state_changes.csv  states.csv  session_log/
summary/      steps.csv  checkpoints.csv  stats.csv  stats.json  questions.csv
              final_answers.csv  state_changes.csv  states.csv
```

`trace.jsonl` records every question with its items, answers, ideology before and after, and push
outcome. `states.csv` holds the full survey state after every step. *Download results (ZIP)* returns
the whole folder.

### 12.3 Reproducibility

Every export records the DTAG version and Git commit, the model key, release and SHA256, the map
provenance, the profile, the persona, the requested and resolved geography and time, the seed,
response mode, fallback mode and LLM model, the initial state, and every question's full
distributions and anchors.

With `resp_mode: max` and fixed persona assignments, native results are deterministic. With `draw`,
they are reproducible given the seed. Language-model steps (persona interpretation, mapping, prose)
can vary between runs. That is why experiments rerun from a fresh respondent and log every question
actually asked.

## 13. HTTP API summary

Interactive OpenAPI docs are served at `http://<host>:<port>/docs`. Main routes:

```text
GET  /api/health   /api/readiness   /api/profiles[/{name}]   /api/models[?family=]
POST /api/models/{family}/{name}/install          GET /api/models/{family}/{name}/status
POST /api/recommend   GET /api/countries   GET /api/eurobarometer/waves   GET /api/eurobarometer/resolve
POST /api/sessions    GET /api/sessions[/{id}]   DELETE /api/sessions/{id}   POST /api/sessions/{id}/reset
POST /api/sessions/{id}/questions                 GET  /api/sessions/{id}/suggestions
POST|GET|DELETE /api/sessions/{id}/sequence
GET  /api/sessions/{id}/ideology-push[?mode=]     POST /api/sessions/{id}/ideology-push/ask|auto
GET  /api/sessions/{id}/landscape                 GET  /api/sessions/{id}/next-questions
GET  /api/sessions/{id}/experiment                POST /api/sessions/{id}/experiment/run
POST /api/experiments/run   GET|DELETE /api/experiments/jobs/{id}   GET /api/experiments
GET  /api/experiments/{folder}/download
GET  /api/sessions/{id}/export?format=json|csv|zip   GET /api/export/bundle?ids=…&labels=…
```

Example:

```bash
SID=$(curl -s -X POST localhost:8000/api/sessions -H 'content-type: application/json' \
  -d '{"profile":"gss2024_cm"}' | python -c 'import json,sys;print(json.load(sys.stdin)["session_id"])')
curl -s -X POST localhost:8000/api/sessions/$SID/questions -H 'content-type: application/json' \
  -d '{"question":"Should abortion be legal for any reason?"}'
curl -s -o session.zip "localhost:8000/api/sessions/$SID/export?format=zip"
```

See [`webapp/README.md`](webapp/README.md#api) for request and response details.

## 14. Environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Language-model key (server-side only). |
| `DTAG_LLM_BACKEND=mock` | Deterministic mock language layer. |
| `DTAG_OPENAI_MODEL` | Override the language model. |
| `DTAG_MODEL_ROOT` | Local model root (§6.2). |
| `DTAG_MODEL_RELEASE`, `DTAG_PUBLIC_BUCKET`, `DTAG_MODEL_MANIFEST_URL` | Public model release (§6.1). |
| `DTAG_MAX_LOADED_MODELS` | Resident models (default 6, LRU). |
| `DTAG_CONFIG`, `DTAG_EURODATES` | Config file and Eurobarometer registry. |
| `DTAG_ASSETS_DIR` | Possible-response and embedding caches (default `~/.cache/dtag/assets`). |
| `DTAG_WEB_DATA_DIR` | Custom profiles. |
| `DTAG_EXPERIMENTS_DIR` | Experiment output folder (default `<repo>/experiments`). |
| `DTAG_HOST`, `DTAG_PORT` | Bind address. |
| `DTAG_MAX_SESSIONS`, `DTAG_SESSION_TTL_HOURS` | In-memory session limits. |
| `DTAG_PASSWORD`, `DTAG_SESSION_SECRET`, `DTAG_AUTH_HOURS` | Access control (§15). |
| `DTAG_RUNTIME_ROOT`, `DTAG_FRONTEND_DIST`, `DTAG_GIT_COMMIT` | Packaging overrides (runtime tree, built UI, reported commit). |

## 15. Deployment and access control

- Set `DTAG_PASSWORD` before exposing the server beyond localhost. Otherwise anyone who can reach it
  can use your OpenAI key. Browsers then get a sign-in page and a signed HttpOnly cookie
  (`DTAG_AUTH_HOURS`, default 12 h). Scripts send `Authorization: Bearer <password>`. Failed logins are
  throttled. `/api/health` stays open for probes.
- Serve it over HTTPS (e.g. Caddy or a cloud load balancer).
- Use one worker process and give it enough memory for the resident models. GSS models are small;
  dense Eurobarometer and Afrobarometer models are larger.
- Put the model root and `DTAG_EXPERIMENTS_DIR` on persistent storage.

See [`webapp/HANDOFF.md`](webapp/HANDOFF.md) for operations and handover notes.

## 16. Testing and readiness checks

```bash
python -m pytest -q                       # everything (native tests skip if models are missing)
cd webapp/tests && DTAG_TEST_OFFLINE=1 pytest -q   # skip the native/network tier
dtag-doctor                               # readiness: files, packages, native bindings, models, maps, poles
python3 scripts/audit_native_maps.py --deep   # load every installed model and check map overlap
```

No test needs an OpenAI key: tests use the mock language layer. The web tests' native tier downloads
`gss/gss_2024` if needed.

## 17. Troubleshooting

| Symptom | Fix |
|---|---|
| "The bundled native LSM extension is not importable" | You are not on CPython 3.13 x86-64 Linux, or glibc < 2.38. Run `bash scripts/build_native_bindings.sh`. |
| Server refuses to start without a key | Set `OPENAI_API_KEY`, or run with `DTAG_LLM_BACKEND=mock`. |
| Model download fails | Check outbound HTTPS to `storage.googleapis.com`, or pre-populate `DTAG_MODEL_ROOT` (§6.4). |
| Landscape spinner on WVS / Afrobarometer / Eurobarometer | Expected: these models are dense and the landscape fills in progressively in the background. |
| No ideology chart | Ideology exists only for GSS. Other surveys still get the landscape and next-question suggestions. |
| Eurobarometer date rejected | The date is ambiguous or not covered. Pick another date or choose the ZA wave explicitly. |
| UI changes not visible after pulling | Hard-refresh the browser. In a source checkout, rebuild with `npm run build`. |
| Everyone logged out after restart | Set a fixed `DTAG_SESSION_SECRET`. |

## 18. Assumptions, limitations and interpretation

- Models represent discrete, categorical survey state spaces. Each wave is a separate model, and
  time selects a wave rather than interpolating between waves.
- Survey weights (e.g. GSS `wtssall`, `wtssps`) appear as ordinary model variables and are not
  applied as sampling weights. Predictions are conditional on the sample, not on the population.
- Persona attributes constrain the state only where compatible survey variables exist. Everything
  else in the persona only shapes the prose.
- Geographic conditioning is limited to the fields each survey contains (see §8). For GSS, place
  is context only.
- Question mapping depends on the semantic map and the language model. Use the *validated* mode or
  the evidence panel to check what a question actually reached. Semantic-fallback and union-fallback
  map rows are weaker evidence and are always labelled as such.
- Conditional predictions are associations, not causal effects. Push and drift experiments measure
  how the model's predictions respond to added information. They do not measure how a person would
  respond to persuasion.
- The ideology index is defined only for GSS, by fixed L/R pole states. It is a model-based summary,
  not a self-report.

DTAG generates a model-conditioned digital twin of survey-response behaviour. It must not be presented
as a real individual, a poll result, or a forecast of anyone's future choices.

## 19. Credits and data sources

Developed by **ZeD Lab, University of Kentucky** (contact: ishanu_ch@uky.edu).

Models are trained on the General Social Survey (NORC at the University of Chicago), the World Values
Survey, Afrobarometer, and Eurobarometer (GESIS data archive). The surveys' producers bear no
responsibility for the models or their use here.
