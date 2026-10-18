# DTAG Quick Start

This gets the DTAG web workbench running so you can question a survey-grounded digital respondent in
about five minutes. For what everything means, see the manual in [README.md](README.md).

**You need:** Python 3.13 on x86-64 Linux (otherwise use Docker, see below), internet access
(models download on demand), and an OpenAI API key (optional for a first look).

## 1. Install and start

```bash
python3.13 -m venv dtag-env && source dtag-env/bin/activate
pip install --upgrade pip
pip install "git+https://github.com/zeroknowledgediscovery/DTAG.git@dev"    # @main for the stable release

export OPENAI_API_KEY="sk-..."      # stays on the server
dtag-web                            # open http://127.0.0.1:8000
```

- **No key yet?** Run `DTAG_LLM_BACKEND=mock dtag-web`. The survey anchors, state and ideology still
  come from the real models; only the prose is a placeholder.
- **Sharing it with others?** Set a password first, so nobody else can spend your OpenAI key:
  `export DTAG_PASSWORD="..."; dtag-web --host 0.0.0.0 --port 8080`. Use HTTPS on the public internet.
- **Updating:** stop the server, then
  `pip install --upgrade --force-reinstall "git+https://github.com/zeroknowledgediscovery/DTAG.git@dev"`,
  restart it, and hard-refresh the browser.

## 2. Use it

1. **Describe the respondent** in the left panel: *Who* (e.g. `35 year old primary school teacher in
   Kenya, listens to the radio`), and optionally *Where* and *When* (a year, or an exact date for
   Eurobarometer). You can also pick a preset such as `gss2024_cm`.
2. **Check the survey model.** DTAG marks the best-matching survey **DEFAULT** (e.g. Kenya 2005 →
   Afrobarometer R3, France 2019-05-15 → Eurobarometer ZA7575, rural Alabama → GSS 2024). It is
   downloaded once and loaded automatically.
3. **Start respondent**, then ask questions: type your own or click a suggestion. Open **Model
   evidence** under an answer to see the survey items and native distributions behind it.
4. **Watch it evolve.** The left column shows the decision landscape. The right column shows the
   ideology trajectory (GSS), the suggested next questions, and the *Auto-push*, *Experiment* and
   *Session* tabs.
5. **Save your work.** Use *Session → Export ▾* for the full log ZIP, JSON or CSV, and *Experiment →
   Rerun ×N* to replay what you did N times with statistics. Each figure has a save button (SVG, PNG
   or PDF).

## Other ways to run it

```bash
# from a clone
git clone https://github.com/zeroknowledgediscovery/DTAG.git && cd DTAG && git checkout dev
python3.13 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cd webapp && cp .env.example .env && ./run.sh            # put OPENAI_API_KEY in .env

# with Docker (any OS)
cd DTAG/webapp && cp .env.example .env && docker compose up --build
```

To run pushes, question sequences or saved experiment recipes without the browser, use
`dtag-experiment` (`python scripts/dtag_experiment.py` from a clone). For example,
`dtag-experiment push --profile gss2024_cm --direction down --steps 10 --runs 20`.
See README §10.7 for details.

Models are stored in `~/.cache/dtag/models/` (change with `DTAG_MODEL_ROOT`). You can pre-download
them with `dtag-models --list`, `dtag-models gss/gss_2024` or `dtag-models --family gss`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `dtag-web: command not found` | Activate the environment: `source dtag-env/bin/activate`. |
| "OPENAI_API_KEY is not configured" | Export the key and restart, or use `DTAG_LLM_BACKEND=mock`. |
| Native extension not importable (macOS, Python ≠ 3.13) | Use Docker, or from a clone run `bash scripts/build_native_bindings.sh` once. |
| Port 8000 in use | Run `dtag-web --port 8080`. |
| Old interface after updating | Reinstall with `--force-reinstall` and hard-refresh the browser. |
| Check the installation | Run `dtag-doctor`, or open `http://127.0.0.1:8000/api/readiness`. |

More: the [manual](README.md) · the [web app and API reference](webapp/README.md) · interactive API
docs at `http://127.0.0.1:8000/docs`.
