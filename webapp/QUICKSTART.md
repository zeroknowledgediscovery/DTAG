# DTAG Web App — Quick Start

Get the DTAG browser workbench running and talk to a survey-grounded digital
respondent in about five minutes.

## What you need

- **Python 3.13** on **x86-64 Linux** (other platforms: see [Troubleshooting](#troubleshooting))
- Internet access (native survey models are downloaded on demand from the public DTAG model store)
- An **OpenAI API key** (optional for a first look — see step 3)

No clone, no cloud credentials and no model downloads are needed up front.

## 1. Install

```bash
python3.13 -m venv dtag-env
source dtag-env/bin/activate

pip install --upgrade pip
pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"
```

This installs the `dtag-web` command (plus `dtag`, `dtag-models`, `dtag-doctor`).

**Updating later:** stop the server, then

```bash
pip install --upgrade --force-reinstall "git+https://github.com/zeroknowledgediscovery/DTAG.git@main"
```

## 2. Set your OpenAI key

```bash
export OPENAI_API_KEY="sk-..."
```

The key stays on the server; the browser never sees it.

## 3. Start the web app

```bash
dtag-web
```

Open **http://127.0.0.1:8000** in your browser.

No OpenAI key yet? Try it with a clearly labelled mock language layer (the
survey anchors, state and ideology are still computed by the real native
models; only the prose is a placeholder):

```bash
DTAG_LLM_BACKEND=mock dtag-web
```

To reach it from other machines or use another port — **set a password
first** so others cannot use your OpenAI key:

```bash
export DTAG_PASSWORD="choose-a-strong-password"
dtag-web --host 0.0.0.0 --port 8080
```

Everyone then sees a sign-in page and uses that password. (For anything on
the public internet, also put it behind HTTPS.)

## 4. Use it

1. **Describe the respondent** (left panel):
   - *Who*: e.g. `35 year old primary school teacher in Kenya, listens to the radio`
   - *Where*: a country (optional if it is in the description)
   - *When*: a year, or an exact date for Eurobarometer (optional; default is the latest survey)

   Or pick a **preset** such as `gss2024_cm` to start from a ready-made respondent.

2. **Check the survey model.** DTAG picks the matching native survey and marks
   it **DEFAULT** (e.g. Kenya 2005 → Afrobarometer R3; France 2019-05-15 →
   Eurobarometer ZA7575; rural Alabama → GSS 2024). Other surveys that also
   fit are listed; click one to switch. The chosen model downloads (once) and
   loads automatically — watch its badge go from *download* to **loaded**.

3. **Click _Start respondent_.**

4. **Ask questions.** Click a suggested question or type your own. Each answer
   has a **Model evidence** panel showing which survey questions were used and
   the native response distributions behind the answer. The respondent's
   survey state carries forward from question to question.

5. On the right: the respondent's model, conditioning, **ideology trajectory**
   (GSS respondents), the session timeline and the current survey state.
   **Export JSON / CSV** saves the full, reproducible session record.
   **Reset respondent** returns to the initial state.

## Other ways to run it

**From a clone** (for development):

```bash
git clone https://github.com/zeroknowledgediscovery/DTAG.git
cd DTAG
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd webapp
cp .env.example .env        # put OPENAI_API_KEY=... in .env
./run.sh                    # http://localhost:8000
```

**With Docker** (any OS with Docker):

```bash
git clone https://github.com/zeroknowledgediscovery/DTAG.git
cd DTAG/webapp
cp .env.example .env        # put OPENAI_API_KEY=... in .env
docker compose up --build   # http://localhost:8000
```

## Where things are stored

| What | Where |
|---|---|
| Downloaded native models (each downloaded once) | `~/.cache/dtag/models/` (set `DTAG_MODEL_ROOT` to change; Docker: the `dtag-data` volume) |
| Custom profiles you save in the browser | `~/.cache/dtag/webapp/profiles.json` (`webapp/data/` when using `run.sh`) |

Pre-download models from the shell if you like:

```bash
dtag-models --list            # public catalog (* = installed)
dtag-models gss/gss_2024      # one model
dtag-models --family gss      # a whole survey family
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `dtag-web: command not found` | Activate the environment: `source dtag-env/bin/activate` |
| Old interface after updating | Stop the server, reinstall with `--force-reinstall` (step 1), restart, hard-refresh the browser |
| “OPENAI_API_KEY is not configured” when starting a respondent | `export OPENAI_API_KEY=...` and restart `dtag-web`, or use `DTAG_LLM_BACKEND=mock` |
| Native extension not importable (macOS, or Python ≠ 3.13) | Use Docker, or from a clone run `bash scripts/build_native_bindings.sh` once |
| Port 8000 already in use | `dtag-web --port 8080` |
| Sign-in page appears | `DTAG_PASSWORD` is set on the server; enter that password (scripts: `Authorization: Bearer <password>`) |
| Check the installation | `dtag-doctor`, or open http://127.0.0.1:8000/api/readiness |

## More

- Full web app guide, API and configuration: [`webapp/README.md`](README.md)
- API reference (interactive): http://127.0.0.1:8000/docs
- DTAG itself (CLI, models, maps): [`README.md`](../README.md)
