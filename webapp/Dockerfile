# DTAG web application image: code, maps, configs, native runtime and built UI.
# Native models are NOT baked in; mount a persistent volume at /data/models.
#
# Build from the repository root:
#   docker build -f webapp/Dockerfile -t dtag-web .
# or: cd webapp && docker compose up --build

# ---- frontend build ------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /src/webapp/frontend
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webapp/frontend/ ./
RUN npm run build

# ---- runtime -------------------------------------------------------------
# The bundled dtag_lsm extension targets CPython 3.13 on glibc >= 2.38.
FROM python:3.13-slim-trixie AS runtime
ARG DTAG_REBUILD_NATIVE=0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DTAG_MODEL_ROOT=/data/models \
    DTAG_ASSETS_DIR=/data/assets \
    DTAG_WEB_DATA_DIR=/data/webapp \
    DTAG_HOST=0.0.0.0 \
    DTAG_PORT=8000

WORKDIR /src
COPY . /src
COPY --from=frontend /src/webapp/frontend/dist /src/webapp/frontend/dist

# Rebuild the native extension only when the prebuilt one does not import
# (or when explicitly requested with --build-arg DTAG_REBUILD_NATIVE=1).
RUN if [ "$DTAG_REBUILD_NATIVE" = "1" ] || ! PYTHONPATH=native/lsm_runtime/python python -c "import dtag_lsm"; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential cmake git file && \
      bash scripts/build_native_bindings.sh && \
      apt-get purge -y build-essential cmake git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* native/lsm_runtime/build; \
    fi \
 && pip install /src \
 && PYTHONPATH=/src/native/lsm_runtime/python python -c "import dtag_lsm; print('native runtime OK')" \
 && useradd --create-home --uid 10001 dtag \
 && mkdir -p /data && chown dtag:dtag /data

USER dtag
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"DTAG_PORT\",\"8000\")}/api/health',timeout=4)"
CMD ["sh", "-c", "exec dtag-web --host \"$DTAG_HOST\" --port \"$DTAG_PORT\""]
