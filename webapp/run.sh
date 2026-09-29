#!/usr/bin/env bash
# Launch the DTAG web application from a source checkout.
#
#   cd webapp && ./run.sh            # production mode: one server on :8000
#   cd webapp && ./run.sh --dev      # FastAPI (:8000, auto-reload) + Vite dev server (:5173)
#
# Settings are read from the environment and, if present, webapp/.env
# (see .env.example). OPENAI_API_KEY stays on the server.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PYTHON="${PYTHON:-python3}"
MODE="${1:-}"

if [[ -f "$HERE/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HERE/.env"
  set +a
fi

export DTAG_WEB_DATA_DIR="${DTAG_WEB_DATA_DIR:-$HERE/data}"
export DTAG_HOST="${DTAG_HOST:-127.0.0.1}"
export DTAG_PORT="${DTAG_PORT:-8000}"
export PYTHONPATH="$HERE/backend:$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"

if ! "$PYTHON" -c "import fastapi, uvicorn, openai, pandas, numpy, yaml, zstandard" 2>/dev/null; then
  echo "Missing Python dependencies for $PYTHON. Install them with:" >&2
  echo "  $PYTHON -m pip install -r $ROOT/requirements.txt" >&2
  exit 1
fi

if ! PYTHONPATH="$ROOT/native/lsm_runtime/python" "$PYTHON" -c "import dtag_lsm" 2>/dev/null; then
  echo "The bundled native LSM extension is not importable for $PYTHON." >&2
  echo "Build it once with: bash $ROOT/scripts/build_native_bindings.sh" >&2
  exit 1
fi

if [[ -z "${OPENAI_API_KEY:-}" && "${DTAG_LLM_BACKEND:-}" != "mock" ]]; then
  echo "WARNING: OPENAI_API_KEY is not set; respondents cannot be started until it is." >&2
fi

if [[ "$MODE" == "--dev" ]]; then
  if ! command -v npm >/dev/null; then
    echo "--dev needs Node.js/npm for the Vite dev server." >&2
    exit 1
  fi
  (cd "$HERE/frontend" && [[ -d node_modules ]] || npm ci)
  "$PYTHON" -m dtag_web --host "$DTAG_HOST" --port "$DTAG_PORT" --reload &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT
  echo "API: http://$DTAG_HOST:$DTAG_PORT/docs   UI (dev): http://localhost:5173"
  cd "$HERE/frontend" && npm run dev
  exit 0
fi

if [[ ! -f "$HERE/frontend/dist/index.html" ]]; then
  if command -v npm >/dev/null; then
    echo "Building frontend..."
    (cd "$HERE/frontend" && npm ci && npm run build)
  else
    echo "WARNING: frontend/dist is missing and npm is unavailable; only the API (/docs) will be served." >&2
  fi
fi

echo "DTAG web application: http://$DTAG_HOST:$DTAG_PORT   (API docs: /docs)"
exec "$PYTHON" -m dtag_web --host "$DTAG_HOST" --port "$DTAG_PORT"
