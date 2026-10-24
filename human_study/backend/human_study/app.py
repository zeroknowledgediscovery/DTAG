"""Public participant application. Researcher/simulator APIs are never mounted."""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import ROOT
from .schemas import Answer, Consent, Start
from .security import Sessions, Throttle
from .service import StudyService, ExportPending, GenerationPending
from .storage import Conflict, IntegrityError, MemoryArchive, MemoryRepository


def configured_service():
    mode = os.environ.get("DTAG_ENV", "local")
    if mode not in ("local", "staging", "production"):
        raise RuntimeError("DTAG_ENV must be local, staging or production")
    fixture = os.environ.get("DTAG_LOCAL_FIXTURE") == "1"
    backend = os.environ.get("DTAG_LLM_BACKEND", "mock" if mode == "local" else "openai")
    if fixture:
        if mode != "local" or backend != "mock":
            raise RuntimeError("computational fixture is restricted to local/mock mode")
        from .local_fixture import LocalFixture, LocalLLM, fixture_config
        return StudyService(fixture_config(), LocalFixture(), LocalLLM(), MemoryRepository(), MemoryArchive())
    from .study_config import StudyConfig
    from .adapter import NativeAdapter
    from .questions import QuestionLLM
    config = StudyConfig.load(os.environ.get("DTAG_STUDY_CONFIG", ROOT / "human_study/config/study.yaml"))
    for name, expected in [("DTAG_STUDY_ID", config.study_id), ("DTAG_MODEL_KEY", config.model_key),
                           ("DTAG_MODEL_RELEASE", config.model_release), ("DTAG_OPENAI_MODEL", config.llm_model)]:
        if os.environ.get(name, expected) != expected:
            raise RuntimeError(f"{name} differs from the immutable instrument")
    if mode != "local":
        if not config.reviewed or not 12 <= len(config.bank("baseline")) <= 15:
            raise RuntimeError("staging/production requires a reviewed 12–15-item baseline instrument")
        if not os.environ.get("DTAG_GCS_BUCKET") or len(os.environ.get("DTAG_COOKIE_SECRET", "")) < 32:
            raise RuntimeError("durable storage and a stable cookie secret are required")
        if backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OpenAI credential is required for the selected language provider")
        if mode == "production" and backend != "openai":
            raise RuntimeError("production requires the live question provider")
        from .storage_firestore import FirestoreRepository
        from .storage_gcs import GCSArchive
        repo = FirestoreRepository(config.study_id, os.environ.get("DTAG_FIRESTORE_DATABASE", "(default)"))
        archive = GCSArchive(os.environ["DTAG_GCS_BUCKET"])
    else:
        repo, archive = MemoryRepository(), MemoryArchive()
    adapter = NativeAdapter(config)
    return StudyService(config, adapter, QuestionLLM(adapter, config, backend), repo, archive)


def create_app(service=None, *, cookie_secret=None, secure=None, frontend_dist=None):
    mode = os.environ.get("DTAG_ENV", "local")
    secure = mode != "local" if secure is None else secure
    secret = cookie_secret or os.environ.get("DTAG_COOKIE_SECRET")
    if mode != "local" and (not secret or len(secret) < 32 or not secure):
        raise RuntimeError("secure cookies and stable >=32-character secret are required")
    sessions = Sessions(secret or secrets.token_urlsafe(48), secure)
    throttle = Throttle()
    enrollment = Throttle(limit=10, maximum=5000)

    @asynccontextmanager
    async def lifespan(app):
        if app.state.service is None:
            # Loading on startup fails closed if native/config/storage requirements are missing.
            app.state.service = configured_service()
        svc = app.state.service
        if mode != "local" and (not svc.repo.durable or not svc.archive.durable):
            raise RuntimeError("nonlocal deployments must use Firestore and GCS")
        svc.repo.probe()
        svc.archive.probe()
        # A versioned, create-only manifest anchors every archive to exact instrument/model provenance.
        svc.archive.put(f"studies/{svc.config.study_id}/manifests/{svc.config.config_hash}.json", {
            "schema_version": "1", "study_configuration": svc.config.model_dump(mode="json"),
            "provenance": svc.adapter.provenance})
        yield

    app = FastAPI(title="Study", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service = service
    app.state.sessions = sessions

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.url.path.startswith("/api/human/"):
            # Origin is required on browser writes; CLI clients should explicitly supply it.
            if request.method == "POST":
                origin = request.headers.get("origin", "")
                expected = f"{request.url.scheme}://{request.url.netloc}"
                if origin != expected:
                    return JSONResponse({"detail": "same-origin request required"}, status_code=403)
                if "application/json" not in request.headers.get("content-type", ""):
                    return JSONResponse({"detail": "JSON required"}, status_code=415)
                try:
                    length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    return JSONResponse({"detail": "invalid request length"}, status_code=400)
                if length > 4096:
                    return JSONResponse({"detail": "request too large"}, status_code=413)
                # Cap chunked bodies too; don't trust Content-Length alone.
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 4096:
                        return JSONResponse({"detail": "request too large"}, status_code=413)
                request._body = bytes(body)
            sid = sessions.sid(request)
            # Cloud Run must use its trusted proxy-header configuration; no forwarded-IP trust here.
            key = sid or (request.client.host if request.client else "unknown")
            if not throttle.allow(key):
                return JSONResponse({"detail": "please wait before retrying"}, status_code=429, headers={"Retry-After": "60"})
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
             "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
             "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    def svc():
        if app.state.service is None:
            raise HTTPException(503, "study is initializing")
        return app.state.service

    def sid(request):
        value = sessions.sid(request)
        if not value:
            raise HTTPException(401, "start a study session first")
        return value

    @app.exception_handler(Conflict)
    async def conflict(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse({"detail": "study session is unavailable"}, status_code=404)

    @app.exception_handler(ExportPending)
    async def pending(_, exc):
        return JSONResponse({"detail": str(exc), "status": "saved_pending_export"}, status_code=503, headers={"Retry-After": "2"})

    @app.exception_handler(GenerationPending)
    async def generating(_, exc):
        return JSONResponse({"detail": str(exc), "status": "preparing_question"}, status_code=503, headers={"Retry-After": "2"})

    @app.exception_handler(IntegrityError)
    async def integrity(_, exc):
        return JSONResponse({"detail": "archive verification failed; contact the study team"}, status_code=503)

    @app.get("/api/human/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/human/readiness")
    def readiness():
        # Public probe reveals no model identities, policy, secrets or participant data.
        try:
            svc().repo.probe()
            svc().archive.probe()
        except Exception:
            raise HTTPException(503, "not ready")
        return {"status": "ready"}

    @app.post("/api/human/start")
    def start(body: Start, request: Request):
        existing = sessions.sid(request)
        if existing is None and not enrollment.allow(request.client.host if request.client else "unknown"):
            raise HTTPException(429, "please wait before opening another session")
        result = svc().start(existing)
        response = JSONResponse(result)
        sessions.set_cookie(response, result["session_id"])
        return response

    @app.get("/api/human/current")
    def current(request: Request):
        return svc().current(sid(request))

    @app.post("/api/human/consent")
    def consent(body: Consent, request: Request):
        return svc().consent(sid(request), body.accepted, body.expected_session_version)

    @app.post("/api/human/answer")
    def answer(body: Answer, request: Request):
        return svc().answer(sid(request), body.model_dump())

    @app.post("/api/human/complete")
    def complete(body: Start, request: Request):
        return svc().complete(sid(request))

    @app.get("/api/human/receipt")
    def receipt(request: Request):
        view = svc().public(svc()._load(sid(request)))
        if view["phase"] != "complete":
            raise HTTPException(409, "study is not complete")
        return {"study_session_id": view["session_id"], "receipt": view["receipt"], "type": "internal_nonpayment_receipt"}

    dist = Path(frontend_dist or ROOT / "human_study/frontend/dist")
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/study", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def page():
        if not (dist / "index.html").is_file():
            raise HTTPException(503, "participant frontend has not been built")
        return FileResponse(dist / "index.html")

    return app
