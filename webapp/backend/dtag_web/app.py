"""FastAPI application exposing the native DTAG engine.

Run with ``dtag-web`` (installed), ``webapp/run.sh`` (source checkout) or
``uvicorn dtag_web.app:app``. OpenAPI documentation is served at ``/docs``.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import DTAG_ROOT  # noqa: F401  (adds DTAG scripts/ to sys.path)
from .schemas import (
    Health,
    ProfileDraft,
    QuestionIn,
    QuestionResult,
    RecommendIn,
    SequenceIn,
    SessionCreate,
    SessionOut,
)
from . import archive
from .auth import PasswordAuth, install as install_auth
from .sequences import SequenceManager, parse_question_lines
from .sessions import SessionStore

import dtag_paths  # noqa: E402
from dtag_engine import DTAGEngine, DTAGEngineError, dtag_version  # noqa: E402


def default_data_dir() -> Path:
    env = os.environ.get("DTAG_WEB_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".cache" / "dtag" / "webapp").resolve()


def create_app(
    engine: Optional[DTAGEngine] = None,
    frontend_dist: Optional[Path] = None,
    auth: Optional[PasswordAuth] = None,
) -> FastAPI:
    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    if engine is None:
        engine = DTAGEngine(profiles_path=data_dir / "profiles.json")
    store = SessionStore(
        max_sessions=int(os.environ.get("DTAG_MAX_SESSIONS", "200")),
        ttl_seconds=float(os.environ.get("DTAG_SESSION_TTL_HOURS", "24")) * 3600,
    )

    app = FastAPI(
        title="DTAG Web API",
        version=dtag_version(),
        description=(
            "Digital Twin Anchored Generation over native Large Science Models. "
            "Survey-response anchors come from native LSM conditional distributions; "
            "the language model selects survey variables and renders prose only."
        ),
    )
    app.state.engine = engine
    app.state.sessions = store
    sequences = SequenceManager()
    app.state.sequences = sequences
    # Shared-password protection when DTAG_PASSWORD is set (see auth.py).
    install_auth(app, auth if auth is not None else PasswordAuth.from_env())

    readiness_cache: Dict[str, Any] = {"at": 0.0, "value": None}
    readiness_lock = threading.Lock()

    @app.exception_handler(DTAGEngineError)
    async def _engine_error(_: Request, exc: DTAGEngineError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def _session(session_id: str):
        es = store.get(session_id)
        if es is None:
            raise HTTPException(404, f"Unknown or expired session: {session_id}")
        return es

    # -- status --------------------------------------------------------------

    @app.get("/api/health", response_model=Health, tags=["status"])
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "dtag_version": dtag_version(),
            "native_runtime": "bundled_persistent",
            "openai_configured": engine.openai_configured,
            "llm_backend": engine.llm_backend,
            "model_release": engine.manifest.release,
            "model_cache_root": str(dtag_paths.model_root()),
            "models_loaded": len(engine.registry.loaded),
            "auth": "password" if app.state.auth is not None else "none",
            "sessions": len(store),
        }

    @app.get("/api/readiness", tags=["status"])
    def readiness(refresh: bool = False) -> Dict[str, Any]:
        with readiness_lock:
            fresh = readiness_cache["value"] is not None and time.time() - readiness_cache["at"] < 300
            if refresh or not fresh:
                if refresh:
                    engine.manifest.get(refresh=True)
                readiness_cache["value"] = engine.readiness()
                readiness_cache["at"] = time.time()
            value = dict(readiness_cache["value"])
        # live counters are cheap; never serve them stale
        value["models_resident"] = {"loaded": len(engine.registry.loaded), "keys": sorted(engine.registry.loaded)}
        value["sessions"] = len(store)
        value["auth"] = "password" if app.state.auth is not None else "none"
        value.pop("_ok", None)
        return value

    # -- profiles --------------------------------------------------------------

    @app.get("/api/profiles", tags=["profiles"])
    def list_profiles() -> List[Dict[str, Any]]:
        return engine.list_profiles()

    @app.get("/api/profiles/{name}", tags=["profiles"])
    def get_profile(name: str) -> Dict[str, Any]:
        try:
            spec = engine.get_profile(name)
        except DTAGEngineError as e:
            raise HTTPException(404, str(e))
        d = engine._profile_listing(engine.apply_overrides(spec, {}))
        return d

    @app.post("/api/profiles/validate", tags=["profiles"])
    def validate_profile(draft: ProfileDraft) -> Dict[str, Any]:
        spec = engine.build_spec(profile=draft.base_profile, overrides=draft.overrides.cleaned(), model_key=draft.model_key)
        out = engine._profile_listing(spec)
        out["capabilities"] = engine.capabilities(spec.model_key)
        return out

    @app.post("/api/profiles", tags=["profiles"])
    def save_profile(draft: ProfileDraft) -> Dict[str, Any]:
        if not draft.name:
            raise HTTPException(400, "name is required")
        spec = engine.build_spec(profile=draft.base_profile, overrides=draft.overrides.cleaned(), model_key=draft.model_key)
        spec.description = draft.description or spec.description
        saved = engine.save_profile(draft.name, spec)
        return engine._profile_listing(saved)

    @app.delete("/api/profiles/{name}", tags=["profiles"])
    def delete_profile(name: str) -> Dict[str, Any]:
        if name in (engine.cfg.get("interactive_profiles") or {}):
            raise HTTPException(400, "Configured profiles cannot be deleted from the web application.")
        if not engine.profile_store.delete(name):
            raise HTTPException(404, f"Unknown custom profile {name!r}")
        return {"deleted": name}

    # -- models ----------------------------------------------------------------

    @app.get("/api/models", tags=["models"])
    def list_models(family: Optional[str] = None, refresh: bool = False) -> List[Dict[str, Any]]:
        return engine.list_models(family=family, refresh=refresh)

    @app.get("/api/models/{family}/{name}", tags=["models"])
    def get_model(family: str, name: str) -> Dict[str, Any]:
        key = engine.validate_model_key(f"{family}/{name}")
        rec = engine.model_record(key)
        rec["capabilities"] = engine.capabilities(key)
        return rec

    @app.get("/api/models/{family}/{name}/status", tags=["models"])
    def model_status(family: str, name: str) -> Dict[str, Any]:
        key = engine.validate_model_key(f"{family}/{name}")
        return engine.registry.status(key).as_dict()

    @app.post("/api/models/{family}/{name}/install", tags=["models"])
    def install_model(family: str, name: str, load: bool = True, wait: bool = False) -> Dict[str, Any]:
        """Install (download + verify + extract) and optionally preload a model.

        By default this starts a background job and returns immediately; poll
        ``/api/models/{key}/status``. ``wait=true`` blocks until done.
        """
        key = engine.validate_model_key(f"{family}/{name}")
        if wait:
            if load:
                engine.registry.load(key)
            else:
                engine.registry.install(key)
            return engine.registry.status(key).as_dict()
        return engine.registry.start_job(key, load=load).as_dict()

    @app.get("/api/maps", tags=["models"])
    def list_maps() -> List[Dict[str, Any]]:
        return engine.list_maps()

    @app.get("/api/maps/{path:path}", tags=["models"])
    def get_map(path: str) -> Dict[str, Any]:
        engine.validate_map_key(path)
        return engine.map_record(path)

    @app.get("/api/geography", tags=["models"])
    def geography() -> Dict[str, Any]:
        """Country/continent names understood by DTAG geographic conditioning."""
        import pipeline as core
        return {
            "countries": [c.title() for c in core.list_supported_countries()],
            "continents": core.list_supported_continents(),
        }

    @app.get("/api/countries", tags=["models"])
    def countries() -> List[Dict[str, Any]]:
        """Countries covered by at least one native model, with the families covering them."""
        return engine.recommender.countries()

    @app.post("/api/recommend", tags=["models"])
    def recommend(body: RecommendIn) -> Dict[str, Any]:
        """Recommend native models for a respondent description, country and time.

        Returns one best candidate per survey family, ranked, with a default and
        the exact overrides (year/date/ZA) to create the session with.
        """
        return engine.recommend(
            persona=body.persona, country=body.country, year=body.year,
            when=body.date, preferred_model=body.preferred_model,
        )

    @app.get("/api/polar-vectors", tags=["models"])
    def polar_sets() -> Dict[str, Any]:
        from dtag_engine import POLAR_VECTOR_SETS
        return {k: {"families": v["families"], "description": v["description"]} for k, v in POLAR_VECTOR_SETS.items()}

    # -- Eurobarometer ---------------------------------------------------------

    @app.get("/api/eurobarometer/waves", tags=["eurobarometer"])
    def eb_waves(year: Optional[int] = Query(None, ge=1900, le=2100)) -> Dict[str, Any]:
        router = engine.eurobarometer
        catalog = {k for k in engine.catalog_keys() if k.startswith("eurobarometer/")}
        by_za: Dict[str, List[str]] = {}
        for k in catalog:
            from dtag_engine import za_of_model
            za = za_of_model(k)
            if za:
                by_za.setdefault(za, []).append(k)
        waves = router.waves_in_year(year) if (year is not None and router.available()) else router.waves()
        rows = []
        for w in waves:
            d = router.wave_dict(w)
            keys = by_za.get(w.za_id, [])
            d["model_key"] = keys[0] if len(keys) == 1 else None
            d["installed"] = bool(keys) and engine.registry.is_installed(keys[0])
            rows.append(d)
        with_dates = {w.za_id for w in router.waves()}
        undated = sorted(k for za, ks in by_za.items() if za not in with_dates for k in ks)
        return {
            "date_registry_available": router.available(),
            "registry": router.registry_path().name if router.available() else None,
            "waves": rows,
            "catalog_models": len(catalog),
            "catalog_models_without_fieldwork_dates": undated,
        }

    @app.get("/api/eurobarometer/resolve", tags=["eurobarometer"])
    def eb_resolve(date: Optional[str] = None, za: Optional[str] = None, year: Optional[int] = None) -> Dict[str, Any]:
        ov: Dict[str, Any] = {}
        if za:
            ov["za"] = za
        elif date:
            ov["date"] = date
        elif year is not None:
            ov["year"] = year
        else:
            raise HTTPException(400, "Provide date, za or year")
        key = next((k for k in engine.catalog_keys() if k.startswith("eurobarometer/")), None)
        if key is None:
            raise HTTPException(503, "No Eurobarometer models in the catalog")
        spec = engine.build_spec(model_key=key, overrides=ov)
        return {
            "requested": ov,
            "resolved_za": spec.za,
            "model_key": spec.model_key,
            "map_key": spec.map_key,
            "temporal": spec.temporal,
            "model": engine.model_record(spec.model_key),
            "warnings": spec.warnings,
        }

    # -- sessions ----------------------------------------------------------------

    @app.post("/api/sessions", response_model=SessionOut, tags=["sessions"])
    def create_session(body: SessionCreate) -> Dict[str, Any]:
        spec = engine.build_spec(profile=body.profile, overrides=body.overrides.cleaned(), model_key=body.model_key)
        if not body.install_if_missing and not engine.registry.is_installed(spec.model_key):
            raise HTTPException(409, f"Model {spec.model_key} is not installed; install it first.")
        es = engine.create_session(spec=spec)
        store.add(es)
        return es.describe()

    @app.get("/api/sessions", tags=["sessions"])
    def list_sessions() -> List[Dict[str, Any]]:
        return [
            {
                "session_id": es.id,
                "created_at": es.created_at,
                "profile": es.spec.name,
                "model_key": es.spec.model_key,
                "questions": es.session.query_count,
            }
            for es in store.all()
        ]

    @app.get("/api/sessions/{session_id}", response_model=SessionOut, tags=["sessions"])
    def get_session(session_id: str) -> Dict[str, Any]:
        return _session(session_id).describe()

    @app.post("/api/sessions/{session_id}/questions", response_model=QuestionResult, tags=["sessions"])
    def ask(session_id: str, body: QuestionIn) -> Dict[str, Any]:
        es = _session(session_id)
        if sequences.active(session_id):
            raise HTTPException(409, "A question sequence is running for this respondent; wait for it or cancel it.")
        try:
            return es.ask(body.question)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/sessions/{session_id}/suggestions", tags=["sessions"])
    def suggestions(session_id: str, n: int = Query(6, ge=1, le=20)) -> List[Dict[str, Any]]:
        """Starter questions that map directly onto the session's survey map."""
        return engine.suggestions(_session(session_id), n=n)

    @app.post("/api/sessions/{session_id}/sequence", tags=["sessions"])
    def start_sequence(session_id: str, body: SequenceIn) -> Dict[str, Any]:
        """Run a question sequence through this respondent (background job).

        Provide ``questions`` (list) or ``text`` (one question per line; blank
        lines, ``#`` comments and a leading ``question`` header are skipped).
        The survey state carries forward across the sequence. Poll
        ``GET .../sequence`` for progress; ``DELETE .../sequence`` cancels.
        """
        es = _session(session_id)
        qs = [q.strip() for q in (body.questions or []) if q and q.strip()]
        if body.text:
            qs += parse_question_lines(body.text)
        if not qs:
            raise HTTPException(400, "No questions found (one question per line).")
        if len(qs) > 500:
            raise HTTPException(400, "At most 500 questions per sequence.")
        too_long = [i + 1 for i, q in enumerate(qs) if len(q) > 2000]
        if too_long:
            raise HTTPException(400, f"Questions longer than 2000 characters at lines {too_long[:5]}")
        try:
            job = sequences.start(es, qs, name=body.name, reset_first=body.reset_first)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return job.snapshot()

    @app.get("/api/sessions/{session_id}/sequence", tags=["sessions"])
    def sequence_status(session_id: str, since: int = Query(0, ge=0)) -> Dict[str, Any]:
        """Progress of the latest sequence; ``since`` returns only newer results."""
        _session(session_id)
        job = sequences.get(session_id)
        if job is None:
            raise HTTPException(404, "No question sequence has been run for this respondent.")
        return job.snapshot(since=since)

    @app.delete("/api/sessions/{session_id}/sequence", tags=["sessions"])
    def cancel_sequence(session_id: str) -> Dict[str, Any]:
        """Stop after the question currently being answered."""
        _session(session_id)
        job = sequences.active(session_id)
        if job is None:
            raise HTTPException(404, "No running question sequence.")
        job.cancel()
        return {"cancelling": job.id}

    @app.post("/api/sessions/{session_id}/reset", response_model=SessionOut, tags=["sessions"])
    def reset(session_id: str) -> Dict[str, Any]:
        es = _session(session_id)
        if sequences.active(session_id):
            raise HTTPException(409, "A question sequence is running; cancel it before resetting.")
        es.reset()
        return es.describe()

    @app.delete("/api/sessions/{session_id}", tags=["sessions"])
    def delete(session_id: str) -> Dict[str, Any]:
        sequences.drop(session_id)
        if not store.remove(session_id):
            raise HTTPException(404, f"Unknown session: {session_id}")
        return {"deleted": session_id}

    def _sequence_since_reset(es) -> Optional[Dict[str, Any]]:
        """The latest sequence job, if its questions are still in the session's history."""
        job = sequences.get(es.id)
        if job is None:
            return None
        snap = job.snapshot()
        have = {(r["query_idx"], r["question"]) for r in es.session.results}
        done = [(r["query_idx"], r["question"]) for r in snap["results"]]
        return snap if done and all(d in have for d in done) else None

    @app.get("/api/sessions/{session_id}/export", tags=["sessions"])
    def export(session_id: str, format: str = Query("json", pattern="^(json|csv|zip)$"),
               label: Optional[str] = Query(None, max_length=40)) -> Response:
        """JSON (full record), CSV (one row per question) or ZIP (complete log for reports)."""
        es = _session(session_id)
        fname = f"dtag_session_{es.spec.model_key.replace('/', '_')}_{es.id[:8]}"
        if format == "zip":
            data = archive.build_session_zip(engine, es, label=label, sequence=_sequence_since_reset(es))
            return Response(data, media_type="application/zip", headers={
                "Content-Disposition": f'attachment; filename="{archive.folder_name(es, label)}.zip"'})
        if format == "csv":
            return PlainTextResponse(
                engine.export_csv(es),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
            )
        return JSONResponse(
            engine.export_session(es),
            headers={"Content-Disposition": f'attachment; filename="{fname}.json"'},
        )

    @app.get("/api/export/bundle", tags=["sessions"])
    def export_bundle(ids: str = Query(..., description="comma-separated session ids"),
                      labels: str = Query("", description="comma-separated labels, same order")) -> Response:
        """One ZIP with a complete log per respondent and an aligned ideology comparison."""
        id_list = [i for i in ids.split(",") if i.strip()]
        if not 1 <= len(id_list) <= 8:
            raise HTTPException(422, "Give 1-8 session ids.")
        lab = [x.strip() for x in labels.split(",")] if labels else []
        lab += [chr(ord("A") + i) for i in range(len(lab), len(id_list))]
        items = []
        for sid, lb in zip(id_list, lab):
            es = _session(sid.strip())
            items.append((es, archive.safe_name(lb) or "X", _sequence_since_reset(es)))
        data = archive.build_bundle_zip(engine, items)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="dtag_bundle_{"_".join(l for _, l, _ in items)}_{stamp}.zip"'})

    # -- frontend ------------------------------------------------------------------

    dist = frontend_dist or Path(os.environ.get("DTAG_FRONTEND_DIST", "") or (DTAG_ROOT / "webapp" / "frontend" / "dist"))
    if (dist / "index.html").is_file():
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (dist / path).resolve()
            if candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend() -> Dict[str, str]:
            return {
                "detail": "DTAG Web API is running. The frontend build was not found; "
                "see /docs for the API or build webapp/frontend (npm run build)."
            }

    return app


app = create_app() if os.environ.get("DTAG_WEB_NO_AUTOAPP", "") != "1" else None
