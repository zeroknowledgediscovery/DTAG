# Build from a clean repository archive; do not send responses or credentials.
# syntax=docker/dockerfile:1
FROM node:22.21.1-bookworm-slim AS frontend
WORKDIR /ui
COPY human_study/frontend/package*.json ./
RUN --mount=type=secret,id=cloud_ca \
    if [ -f /run/secrets/cloud_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/cloud_ca; fi; npm ci
COPY human_study/frontend/index.html human_study/frontend/tsconfig.json human_study/frontend/vite.config.ts ./
COPY human_study/frontend/src ./src
RUN npm run build

# Same ABI-compatible base as the existing DTAG application.
FROM python:3.13-slim-trixie AS runtime
ARG DTAG_CODE_COMMIT=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/src/human_study/backend:/src/scripts:/src \
    DTAG_CODE_COMMIT=$DTAG_CODE_COMMIT DTAG_ENV=staging \
    DTAG_MODEL_ROOT=/tmp/dtag/models DTAG_ASSETS_DIR=/tmp/dtag/assets PORT=8080
WORKDIR /src
COPY requirements.txt ./
COPY scripts ./scripts
COPY configs ./configs
COPY maps ./maps
COPY assets/polar_vectors ./assets/polar_vectors
COPY native/lsm_runtime ./native/lsm_runtime
COPY optimizer ./optimizer
COPY human_study/backend ./human_study/backend
COPY human_study/requirements.txt ./human_study/requirements.txt
COPY human_study/config ./human_study/config
COPY --from=frontend /ui/dist ./human_study/frontend/dist
RUN --mount=type=secret,id=cloud_ca \
    if [ -f /run/secrets/cloud_ca ]; then export PIP_CERT=/run/secrets/cloud_ca SSL_CERT_FILE=/run/secrets/cloud_ca; fi; \
    if ! PYTHONPATH=native/lsm_runtime/python python -c 'import dtag_lsm'; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential cmake git file && \
      bash scripts/build_native_bindings.sh && \
      apt-get purge -y build-essential cmake git && apt-get autoremove -y && \
      rm -rf /var/lib/apt/lists/* native/lsm_runtime/build; \
    fi \
 && pip install -r human_study/requirements.txt \
 && PYTHONPATH=native/lsm_runtime/python python -c 'import dtag_lsm; print("native runtime OK")' \
 && useradd --create-home --uid 10001 study
USER study
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/human/health',timeout=4)"
CMD ["python", "-m", "human_study"]
