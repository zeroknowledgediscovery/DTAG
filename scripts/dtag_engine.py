#!/usr/bin/env python3
"""DTAG engine: catalog, model registry, profiles and respondent sessions.

The engine is the process-level owner of everything that can be shared
between respondents, and the factory for isolated ``DTAGSession`` objects:

* model catalog  -- public manifest + installed models + configured models
* map inventory  -- repository semantic maps and model->map conventions
* ``ModelRegistry`` -- downloads (via ``fetch_models``) and one persistent
  native runtime per model key for the life of the process
* profiles       -- configured ``interactive_profiles`` (resolved exactly as
  ``interactive.py`` does) plus validated custom profiles
* Eurobarometer  -- fieldwork-date routing via ``eurobarometer_dates``
* sessions       -- ``engine.create_session(profile=..., overrides=...)``

Scientific inference lives in ``dtag_session`` / ``pipeline``; this module
never predicts survey responses itself.

Example::

    engine = DTAGEngine()
    s = engine.create_session(profile="gss2024_cm")
    result = s.ask("What are your thoughts about immigration?")
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

import dtag_paths
import eurobarometer_dates as ebdates
import eurobarometer_native as ebnative
import fetch_models
import interactive
import pipeline as core
import pipeline_localized as localized
from dtag_session import (
    DTAGConfigError,
    DTAGSession,
    ModelContext,
    PolarGeometry,
    SessionConfig,
    build_polar_geometry,
    default_client_factory,
)
from model_backend import NativeLSMBackend, _read_native_columns

REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ("gss", "afrobarometer", "wvs", "eurobarometer")
FAMILY_LABELS = {
    "gss": "GSS",
    "afrobarometer": "Afrobarometer",
    "wvs": "World Values Survey",
    "eurobarometer": "Eurobarometer",
}

# Polar reference vectors, registered with the survey families they are valid
# for. GSS vectors must never be reused for WVS/Afrobarometer/Eurobarometer.
POLAR_VECTOR_SETS: Dict[str, Dict[str, Any]] = {
    "gss_default": {
        "path": "assets/polar_vectors/polar_vectors.csv",
        "families": ["gss"],
        "description": "GSS left/right polar reference states (L/R columns).",
    },
}

# Session parameters a profile/override may set (and their bounds).
RUN_PARAM_BOUNDS: Dict[str, Tuple[type, Any, Any]] = {
    "k": (int, 1, 200),
    "prefilter": (int, 1, 2000),
    "min_map_score": (float, 0.0, 20.0),
    "semantic_k": (int, 1, 50),
    "semantic_prefilter": (int, 1, 500),
    "semantic_min_confidence": (float, 0.0, 1.0),
    "max_assign": (int, 0, 200),
    "assign_prefilter": (int, 1, 5000),
    "seed": (int, 0, 2**31 - 1),
    "state_keep": (int, 1, 5000),
}
RUN_PARAM_CHOICES: Dict[str, Tuple[str, ...]] = {
    "semantic_fallback": ("off", "answer_only", "update_state"),
    "resp_mode": ("max", "draw"),
    "semantic_resp_mode": ("max", "draw"),
}
SERVER_RUN_PARAMS = ("openai_model", "semantic_embedding_model")

OVERRIDE_FIELDS = (
    "persona", "country", "continent", "year", "date", "za", "model_key",
    "map_key", "ideology", "polar_set",
) + tuple(RUN_PARAM_BOUNDS) + tuple(RUN_PARAM_CHOICES)

ZA_RE = re.compile(r"^(?:ZA)?(\d{1,5})$", re.I)
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class DTAGEngineError(ValueError):
    """User-correctable engine error (bad key, bad override, ambiguous date...)."""


# -----------------------------
# Small helpers
# -----------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dtag_version() -> str:
    p = REPO_ROOT / "VERSION"
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def git_commit() -> Optional[str]:
    env = os.environ.get("DTAG_GIT_COMMIT", "").strip()
    if env:
        return env
    if not (REPO_ROOT / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def family_of(key: str) -> str:
    return str(key).split("/", 1)[0]


def model_label(key: str) -> str:
    fam, name = key.split("/", 1)
    if fam == "gss":
        m = re.fullmatch(r"gss_(\d{4})", name)
        return f"GSS {m.group(1)}" if m else name
    if fam == "afrobarometer":
        m = re.fullmatch(r"r(\d+)", name, re.I)
        return f"Afrobarometer R{m.group(1)}" if m else name
    if fam == "wvs":
        return "WVS7 pooled" if name == "wvs7_pooled" else name
    if fam == "eurobarometer":
        parts = name.split("_", 1)
        return f"Eurobarometer {parts[0]}" + (f" ({parts[1]})" if len(parts) > 1 else "")
    return key


def model_year(key: str) -> Optional[int]:
    m = re.fullmatch(r"gss/gss_(\d{4})", key)
    return int(m.group(1)) if m else None


def za_of_model(key: str) -> Optional[str]:
    m = re.fullmatch(r"eurobarometer/(ZA\d+)(?:_.*)?", key, re.I)
    return m.group(1).upper() if m else None


def normalize_za(value: str) -> str:
    m = ZA_RE.fullmatch(str(value).strip())
    if not m:
        raise DTAGEngineError(f"Invalid Eurobarometer ZA identifier: {value!r}")
    return "ZA" + m.group(1).zfill(4)


def maps_root() -> Path:
    return REPO_ROOT / "maps"


def map_inventory() -> Dict[str, Path]:
    """Repository semantic maps keyed by path relative to ``maps/``."""
    root = maps_root()
    out: Dict[str, Path] = {}
    if root.is_dir():
        for p in sorted(root.rglob("*.csv")):
            out[p.relative_to(root).as_posix()] = p.resolve()
    return out


def canonical_map_key(model_key: str) -> Optional[str]:
    fam, name = model_key.split("/", 1)
    if fam == "gss":
        cand = f"gss/{name}_map.csv"
    elif fam == "afrobarometer":
        cand = f"afromap/afrobarometer_{name.lower()}_map.csv"
    elif fam == "wvs":
        cand = "wvs7_variable_question_map.csv" if name.startswith("wvs7") else ""
    elif fam == "eurobarometer":
        za = za_of_model(model_key)
        cand = f"eurobarometer/{za}_map.csv" if za else ""
    else:
        cand = ""
    if cand and (maps_root() / cand).is_file():
        return cand
    return None


def map_family(map_key: str) -> Optional[str]:
    if map_key.startswith("gss/"):
        return "gss"
    if map_key.startswith("afromap/"):
        return "afrobarometer"
    if map_key.startswith("wvs"):
        return "wvs"
    if map_key.startswith("eurobarometer/"):
        return "eurobarometer"
    return None


def model_key_from_path(path: str | Path) -> Optional[str]:
    """Canonical key (e.g. ``gss/gss_2024``) for a configured model path."""
    s = str(path).replace("\\", "/")
    if s.startswith("models/lsm/"):
        key = s[len("models/lsm/"):].strip("/")
    else:
        try:
            key = Path(path).resolve().relative_to(dtag_paths.model_root()).as_posix()
        except Exception:
            return None
    return key if fetch_models.MODEL_KEY_RE.fullmatch(key) else None


def model_dir(key: str) -> Path:
    return dtag_paths.model_root() / key


def _polar_set_for_path(path: str) -> Optional[str]:
    if not path:
        return None
    rp = (REPO_ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    for k, v in POLAR_VECTOR_SETS.items():
        if (REPO_ROOT / v["path"]).resolve() == rp:
            return k
    return None


# -----------------------------
# Manifest
# -----------------------------

class ManifestCache:
    def __init__(self, ttl: float = 900.0):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._manifest: Optional[dict] = None
        self._fetched = 0.0
        self.error: Optional[str] = None

    @property
    def release(self) -> str:
        return fetch_models.DEFAULT_RELEASE

    @property
    def url(self) -> str:
        return fetch_models.manifest_url(self.release)

    def get(self, refresh: bool = False) -> Optional[dict]:
        with self._lock:
            fresh = self._manifest is not None and (time.time() - self._fetched) < self.ttl
            if fresh and not refresh:
                return self._manifest
            try:
                self._manifest = fetch_models.load_manifest(self.release, timeout=20)
                self._fetched = time.time()
                self.error = None
            except Exception as e:  # keep a stale manifest if we had one
                self.error = f"{type(e).__name__}: {e}"
                self._fetched = time.time()
            return self._manifest

    def set(self, manifest: dict) -> None:
        with self._lock:
            self._manifest = manifest
            self._fetched = time.time()
            self.error = None


# -----------------------------
# Model registry (process-level cache)
# -----------------------------

class LockedBackend:
    """Serialises native inference on a shared runtime.

    The C++ runtime releases the GIL; until concurrent calls on one runtime
    are stress-tested, predictions/distances on a shared model are serialised.
    """

    def __init__(self, backend: NativeLSMBackend, lock: threading.Lock):
        self._backend = backend
        self._lock = lock

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def predict_distributions(self, *a, **kw):
        with self._lock:
            return self._backend.predict_distributions(*a, **kw)

    def qdistance(self, *a, **kw):
        with self._lock:
            return self._backend.qdistance(*a, **kw)

    def distances_to_state(self, *a, **kw):
        with self._lock:
            return self._backend.distances_to_state(*a, **kw)


@dataclass
class ModelStatus:
    key: str
    state: str = "not_installed"  # not_installed|downloading|verifying|extracting|installed|loading|loaded|error
    done_bytes: int = 0
    total_bytes: int = 0
    error: Optional[str] = None
    updated: str = field(default_factory=_now)
    job_running: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "state": self.state,
            "done_bytes": self.done_bytes,
            "total_bytes": self.total_bytes,
            "error": self.error,
            "updated": self.updated,
            "job_running": self.job_running,
        }


class LoadedModel:
    """One native model resident in memory, shared by sessions."""

    def __init__(self, key: str, path: Path, backend: NativeLSMBackend, load_seconds: float, assets_dir: str):
        self.key = key
        self.path = path
        self.backend = backend
        self.inference_lock = threading.Lock()
        self.model = LockedBackend(backend, self.inference_lock)
        self.load_seconds = load_seconds
        self.loaded_at = _now()
        self.assets_dir = assets_dir
        self._lock = threading.Lock()
        self._possible: Optional[Dict[str, List[str]]] = None
        self._contexts: Dict[str, ModelContext] = {}
        self._polar: Dict[str, PolarGeometry] = {}

    @property
    def possible(self) -> Dict[str, List[str]]:
        with self._lock:
            if self._possible is None:
                self._possible = core.get_possible_responses_cached(self.model, str(self.path), assets_dir=self.assets_dir)
            return self._possible

    def context(self, map_path: Path) -> ModelContext:
        key = str(Path(map_path).resolve())
        possible = self.possible
        with self._lock:
            ctx = self._contexts.get(key)
            if ctx is None:
                ctx = ModelContext(self.model, str(self.path), key, assets_dir=self.assets_dir, possible=possible)
                self._contexts[key] = ctx
            return ctx

    def polar(self, ctx: ModelContext, polar_path: str) -> PolarGeometry:
        """Polar geometry depends only on the model and the vector file."""
        with self._lock:
            g = self._polar.get(polar_path)
            if g is None:
                g = build_polar_geometry(ctx, polar_path, no_ideology=False)
                self._polar[polar_path] = g
            return g

    def info(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "runtime": getattr(self.backend, "runtime_kind", "unknown"),
            "features": len(self.backend.feature_names),
            "usable_trees": len(self.backend.usable_tree_ids),
            "load_seconds": round(self.load_seconds, 3),
            "loaded_at": self.loaded_at,
        }


class ModelRegistry:
    """Downloads models once and keeps one persistent native runtime per key."""

    def __init__(self, manifest: ManifestCache, assets_dir: str, loader: Optional[Callable[[Path], NativeLSMBackend]] = None):
        self.manifest = manifest
        self.assets_dir = assets_dir
        self._loader = loader or (lambda p: NativeLSMBackend(p, preload=True))
        self.loaded: Dict[str, LoadedModel] = {}
        self._status: Dict[str, ModelStatus] = {}
        self._key_locks: Dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self.load_events: List[Dict[str, Any]] = []
        self.download_events: List[Dict[str, Any]] = []

    # -- status -------------------------------------------------------------

    def _key_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _set(self, key: str, **kw: Any) -> None:
        with self._lock:
            st = self._status.setdefault(key, ModelStatus(key=key))
            for k, v in kw.items():
                setattr(st, k, v)
            st.updated = _now()

    def is_installed(self, key: str) -> bool:
        return fetch_models.installed(dtag_paths.model_root(), key)

    def status(self, key: str) -> ModelStatus:
        with self._lock:
            st = self._status.get(key)
            if st is not None and (st.job_running or st.state in {"loaded", "error", "loading", "downloading", "verifying", "extracting"}):
                return ModelStatus(**st.__dict__)
        state = "loaded" if key in self.loaded else ("installed" if self.is_installed(key) else "not_installed")
        return ModelStatus(key=key, state=state)

    # -- install/load -------------------------------------------------------

    def install(self, key: str) -> Path:
        """Synchronously ensure ``key`` is installed on disk (download once)."""
        key = fetch_models.validate_model_key(key)
        root = dtag_paths.model_root()
        with self._key_lock(key):
            if self.is_installed(key):
                if key not in self.loaded:
                    self._set(key, state="installed", error=None)
                return root / key
            manifest = self.manifest.get()
            if manifest is None:
                raise DTAGEngineError(
                    f"Model {key} is not installed and the public manifest is unreachable: {self.manifest.error}"
                )
            if key not in manifest.get("models", {}):
                raise DTAGEngineError(f"Model {key} is not in public release {manifest.get('release')}")

            def progress(stage: str, done: int, total: int) -> None:
                self._set(key, state=stage, done_bytes=done, total_bytes=total)

            try:
                t0 = time.time()
                path = fetch_models.fetch_one(root, manifest, key, progress=progress, log=lambda *_: None)
                self.download_events.append({"key": key, "seconds": time.time() - t0, "at": _now()})
            except Exception as e:
                self._set(key, state="error", error=str(e))
                raise
            self._set(key, state="installed", error=None)
            return path

    def load(self, key: str) -> LoadedModel:
        """Install if needed, then return the process-wide loaded model."""
        key = fetch_models.validate_model_key(key)
        lm = self.loaded.get(key)
        if lm is not None:
            return lm
        path = self.install(key)
        with self._key_lock(key):
            lm = self.loaded.get(key)
            if lm is not None:
                return lm
            self._set(key, state="loading", error=None)
            try:
                t0 = time.time()
                backend = self._loader(path)
                secs = time.time() - t0
            except Exception as e:
                self._set(key, state="error", error=f"native load failed: {e}")
                raise
            lm = LoadedModel(key, path, backend, secs, self.assets_dir)
            self.loaded[key] = lm
            self.load_events.append({"key": key, "seconds": secs, "at": _now()})
            self._set(key, state="loaded", error=None)
            return lm

    def start_job(self, key: str, load: bool = True) -> ModelStatus:
        """Install (and optionally load) in a background thread."""
        key = fetch_models.validate_model_key(key)
        with self._lock:
            st = self._status.setdefault(key, ModelStatus(key=key))
            if st.job_running:
                return ModelStatus(**st.__dict__)
            st.job_running = True
            st.error = None

        def run() -> None:
            try:
                if load:
                    self.load(key)
                else:
                    self.install(key)
            except Exception as e:
                self._set(key, state="error", error=str(e))
            finally:
                self._set(key, job_running=False)

        threading.Thread(target=run, name=f"dtag-install-{key}", daemon=True).start()
        return self.status(key)

    def unload(self, key: str) -> bool:
        with self._key_lock(key):
            lm = self.loaded.pop(key, None)
            if lm is not None:
                self._set(key, state="installed")
            return lm is not None


# -----------------------------
# Eurobarometer routing
# -----------------------------

class EurobarometerRouter:
    """Fieldwork-date routing over the two-column ZA/date registry.

    The registry is read from ``DTAG_EURODATES`` or ``configs/eurodates.csv``
    when present. Without it, only explicit ZA selection is possible.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: Optional[Tuple[str, float, List[ebdates.EurobarometerWave]]] = None

    def registry_path(self) -> Optional[Path]:
        env = os.environ.get("DTAG_EURODATES", "").strip()
        p = Path(env).expanduser() if env else REPO_ROOT / "configs" / "eurodates.csv"
        return p.resolve() if p.is_file() else None

    def waves(self) -> List[ebdates.EurobarometerWave]:
        p = self.registry_path()
        if p is None:
            return []
        mtime = p.stat().st_mtime
        with self._lock:
            if self._cache and self._cache[0] == str(p) and self._cache[1] == mtime:
                return self._cache[2]
            waves = ebdates.load_registry(p)
            self._cache = (str(p), mtime, waves)
            return waves

    def available(self) -> bool:
        return self.registry_path() is not None

    def wave_for_za(self, za: str) -> Optional[ebdates.EurobarometerWave]:
        for w in self.waves():
            if w.za_id == za:
                return w
        return None

    def resolve_date(self, when: date) -> ebdates.EurobarometerWave:
        if not self.available():
            raise DTAGEngineError(
                "Eurobarometer date routing is unavailable: no fieldwork-date registry "
                "(configs/eurodates.csv or DTAG_EURODATES). Choose an explicit ZA."
            )
        try:
            return ebdates.resolve_exact_date(self.waves(), when)
        except ValueError as e:
            raise DTAGEngineError(str(e).replace("--za", "an explicit ZA")) from e

    def waves_in_year(self, year: int) -> List[ebdates.EurobarometerWave]:
        return ebdates.waves_in_year(self.waves(), year)

    @staticmethod
    def wave_dict(w: ebdates.EurobarometerWave) -> Dict[str, Any]:
        return {
            "za": w.za_id,
            "fieldwork_start": w.start_date.isoformat(),
            "fieldwork_end": w.end_date.isoformat(),
            "fieldwork_raw": w.raw_fieldwork,
            "start_precision": w.start_precision,
            "end_precision": w.end_precision,
            "auto_select": w.auto_select,
        }


# -----------------------------
# Profile specs
# -----------------------------

def _coerce_param(name: str, value: Any) -> Any:
    if name in RUN_PARAM_CHOICES:
        v = str(value).strip()
        if v not in RUN_PARAM_CHOICES[name]:
            raise DTAGEngineError(f"{name} must be one of {list(RUN_PARAM_CHOICES[name])}")
        return v
    typ, lo, hi = RUN_PARAM_BOUNDS[name]
    try:
        v = typ(value)
    except Exception:
        raise DTAGEngineError(f"{name} must be a {typ.__name__}")
    if not (lo <= v <= hi):
        raise DTAGEngineError(f"{name} must be within [{lo}, {hi}]")
    return v


def _clean_text(name: str, value: Any, max_len: int) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\x00", "").strip()
    if len(s) > max_len:
        raise DTAGEngineError(f"{name} is too long (max {max_len} characters)")
    return s


@dataclass
class ProfileSpec:
    """Validated, fully resolved description of a respondent to create."""

    name: str
    source: str  # configured | custom | adhoc
    description: str
    family: str
    model_key: str
    map_key: str
    persona: str
    country: str = ""
    continent: str = ""
    year: Optional[int] = None
    date: Optional[str] = None
    za: Optional[str] = None
    polar_set: Optional[str] = None
    ideology: bool = False
    base_profile: Optional[str] = None
    run: Dict[str, Any] = field(default_factory=dict)
    temporal: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "family": self.family,
            "model_key": self.model_key,
            "model_label": model_label(self.model_key),
            "map_key": self.map_key,
            "persona": self.persona,
            "country": self.country,
            "continent": self.continent,
            "year": self.year,
            "date": self.date,
            "za": self.za,
            "polar_set": self.polar_set,
            "ideology": self.ideology,
            "base_profile": self.base_profile,
            "run": dict(self.run),
            "temporal": dict(self.temporal),
            "warnings": list(self.warnings),
        }

    def storable(self) -> Dict[str, Any]:
        d = self.as_dict()
        for k in ("model_label", "temporal", "warnings", "source"):
            d.pop(k, None)
        # Store what the user asked for: a date-routed profile keeps its date
        # (re-resolved on load); the resolved ZA is derived, not requested.
        if d.get("date"):
            d.pop("za", None)
        return d


class ProfileStore:
    """Custom profiles persisted as JSON (never mutates dtag_config.yaml)."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Dict[str, Any]]:
        if self.path is None or not self.path.is_file():
            return {}
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def save(self, name: str, data: Dict[str, Any]) -> None:
        if self.path is None:
            raise DTAGEngineError("No custom-profile storage is configured.")
        with self._lock:
            all_ = self.load()
            all_[name] = data
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(all_, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def delete(self, name: str) -> bool:
        if self.path is None:
            return False
        with self._lock:
            all_ = self.load()
            if name not in all_:
                return False
            all_.pop(name)
            self.path.write_text(json.dumps(all_, indent=2, ensure_ascii=False), encoding="utf-8")
            return True


# -----------------------------
# Engine sessions
# -----------------------------

class EngineSession:
    """A ``DTAGSession`` plus the provenance of how it was created."""

    def __init__(self, engine: "DTAGEngine", spec: ProfileSpec, session: DTAGSession, loaded: LoadedModel, init_info: Dict[str, Any]):
        self.id = uuid.uuid4().hex
        self.created_at = _now()
        self.last_used = time.time()
        self.engine = engine
        self.spec = spec
        self.session = session
        self.loaded = loaded
        self.init_info = init_info
        self.geographic_conditioning = engine.geographic_conditioning(spec, session)
        self.temporal_conditioning = engine.temporal_conditioning(spec, session)

    def ask(self, question: str) -> Dict[str, Any]:
        self.last_used = time.time()
        r = self.session.ask(question)
        out = dict(r)
        out.pop("record", None)
        out["geographic_conditioning"] = self.geographic_conditioning
        out["temporal_conditioning"] = self.temporal_conditioning
        return out

    def reset(self) -> None:
        self.last_used = time.time()
        self.session.reset()

    def ideology_summary(self) -> Dict[str, Any]:
        s = self.session
        cur = s.ideology_series[-1][1] if s.ideology_enabled and s.ideology_series else None
        return {
            "enabled": s.ideology_enabled,
            "initial": s.ideology0,
            "current": cur,
            "change_from_initial": (cur - s.ideology0) if (cur is not None and s.ideology0 is not None) else None,
            "disable_reason": None if s.ideology_enabled else (
                s.polar.disable_reason or "Ideology trajectory is not available for this survey/profile."
            ),
            "polar_set": self.spec.polar_set if s.ideology_enabled else None,
            "convention": "I(s) = (d(sL, s) - d(sR, s)) / d(sL, sR); native LSM qdistance; L/R are the columns of the registered polar-vector file.",
            "trajectory": s.ideology_trajectory() if s.ideology_enabled else [],
        }

    def model_info(self) -> Dict[str, Any]:
        return self.engine.model_record(self.spec.model_key)

    def describe(self) -> Dict[str, Any]:
        s = self.session
        return {
            "session_id": self.id,
            "created_at": self.created_at,
            "resolved_profile": self.spec.as_dict(),
            "model": self.model_info(),
            "map": self.engine.map_record(self.spec.map_key),
            "persona_text": s.persona,
            "initial_state": s.initial_state(),
            "current_state": dict(s.state),
            "question_count": s.query_count,
            "persona_assignments": {
                "llm_raw": s.persona_assignments_llm_raw,
                "dropped": s.persona_assignments_dropped,
                "rationale": s.persona_rationale,
                "forced": s.forced_assignments,
            },
            "geographic_conditioning": self.geographic_conditioning,
            "temporal_conditioning": self.temporal_conditioning,
            "ideology": self.ideology_summary(),
            "config": s.config.to_dict(),
            "llm": self.init_info.get("llm"),
            "init_timings": self.init_info.get("timings", {}),
            "history": [self._history_item(r) for r in s.results],
        }

    @staticmethod
    def _history_item(r: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(r)
        out.pop("record", None)
        return out


# -----------------------------
# Engine
# -----------------------------

class DTAGEngine:
    def __init__(
        self,
        config_path: Optional[str | Path] = None,
        assets_dir: Optional[str | Path] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        profiles_path: Optional[str | Path] = None,
        llm_backend: Optional[str] = None,
        model_loader: Optional[Callable[[Path], NativeLSMBackend]] = None,
    ):
        cp = config_path or os.environ.get("DTAG_CONFIG") or (REPO_ROOT / "configs" / "dtag_config.yaml")
        self.config_path = Path(cp).expanduser().resolve()
        self.config_root = interactive.config_root(self.config_path)
        self.cfg = interactive.load_config(self.config_path)
        ad = assets_dir or os.environ.get("DTAG_ASSETS_DIR") or (Path.home() / ".cache" / "dtag" / "assets")
        self.assets_dir = str(Path(ad).expanduser().resolve())
        Path(self.assets_dir).mkdir(parents=True, exist_ok=True)
        self.llm_backend = (llm_backend or os.environ.get("DTAG_LLM_BACKEND", "openai")).strip().lower() or "openai"
        if client_factory is not None:
            self.client_factory = client_factory
        elif self.llm_backend == "mock":
            from dtag_mock_llm import MockOpenAI
            self.client_factory = MockOpenAI
        else:
            self.client_factory = default_client_factory
        self.openai_model_override = os.environ.get("DTAG_OPENAI_MODEL", "").strip() or None
        self.manifest = ManifestCache()
        self.registry = ModelRegistry(self.manifest, self.assets_dir, loader=model_loader)
        self.eurobarometer = EurobarometerRouter()
        self.profile_store = ProfileStore(Path(profiles_path).expanduser().resolve() if profiles_path else None)
        self._capabilities: Dict[str, Dict[str, Any]] = {}
        self._cap_lock = threading.Lock()

    # -- environment --------------------------------------------------------

    @property
    def openai_configured(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())

    @property
    def llm_ready(self) -> bool:
        return self.llm_backend == "mock" or self.openai_configured

    def llm_info(self, openai_model: str) -> Dict[str, Any]:
        return {
            "backend": self.llm_backend,
            "openai_model": openai_model,
            "mock": self.llm_backend == "mock",
            "note": "Mock LLM: deterministic stand-in for variable selection and prose. Native LSM anchors are real."
            if self.llm_backend == "mock" else None,
        }

    # -- catalog -------------------------------------------------------------

    def installed_keys(self) -> List[str]:
        root = dtag_paths.model_root()
        out = []
        for fam in FAMILIES:
            d = root / fam
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if p.name.startswith("."):
                    continue
                if (p / "source_maps").is_dir() and (p / "trees" / "binary").is_dir():
                    out.append(f"{fam}/{p.name}")
        return out

    def configured_model_keys(self) -> Dict[str, str]:
        out = {}
        for name, path in (self.cfg.get("models", {}) or {}).items():
            k = model_key_from_path(str(path))
            if k:
                out[str(name)] = k
        return out

    def catalog_keys(self, refresh: bool = False) -> List[str]:
        keys = set(self.installed_keys()) | set(self.configured_model_keys().values())
        m = self.manifest.get(refresh=refresh)
        if m:
            keys |= set(m.get("models", {}))
        return sorted(keys)

    def validate_model_key(self, key: str) -> str:
        try:
            key = fetch_models.validate_model_key(key)
        except ValueError as e:
            raise DTAGEngineError(str(e))
        if key not in set(self.catalog_keys()):
            raise DTAGEngineError(f"Unknown DTAG model key: {key}")
        return key

    def validate_map_key(self, key: str) -> str:
        inv = map_inventory()
        if key not in inv:
            raise DTAGEngineError(f"Unknown semantic map: {key}")
        return key

    def model_record(self, key: str) -> Dict[str, Any]:
        m = self.manifest.get() or {}
        entry = (m.get("models") or {}).get(key)
        fam = family_of(key)
        st = self.registry.status(key)
        installed = self.registry.is_installed(key)
        map_key = canonical_map_key(key)
        polar_sets = [k for k, v in POLAR_VECTOR_SETS.items() if fam in v["families"]]
        rec = {
            "key": key,
            "family": fam,
            "family_label": FAMILY_LABELS.get(fam, fam),
            "name": key.split("/", 1)[1],
            "label": model_label(key),
            "year": model_year(key),
            "za": za_of_model(key),
            "installed": installed,
            "loaded": key in self.registry.loaded,
            "status": st.as_dict(),
            "map_available": map_key is not None,
            "map_key": map_key,
            "ideology_available": bool(polar_sets),
            "polar_sets": polar_sets,
            "in_public_release": entry is not None,
            "archive_bytes": entry.get("size_bytes") if entry else None,
            "sha256": entry.get("sha256") if entry else None,
            "archive": entry.get("archive") if entry else None,
            "release": m.get("release") if entry else None,
            "configured_profiles": [n for n, p in self.configured_profile_models().items() if p == key],
        }
        if key in self.registry.loaded:
            rec["runtime"] = self.registry.loaded[key].info()
        if fam == "eurobarometer" and rec["za"]:
            w = self.eurobarometer.wave_for_za(rec["za"]) if self.eurobarometer.available() else None
            rec["fieldwork"] = EurobarometerRouter.wave_dict(w) if w else None
        return rec

    def list_models(self, family: Optional[str] = None, refresh: bool = False) -> List[Dict[str, Any]]:
        keys = self.catalog_keys(refresh=refresh)
        if family:
            keys = [k for k in keys if family_of(k) == family]
        return [self.model_record(k) for k in keys]

    def map_record(self, map_key: str) -> Dict[str, Any]:
        inv = map_inventory()
        p = inv.get(map_key)
        rec: Dict[str, Any] = {"key": map_key, "family": map_family(map_key), "available": p is not None}
        if p is None:
            return rec
        try:
            with p.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                cols = reader.fieldnames or []
                counts: Dict[str, int] = {}
                n = 0
                for row in reader:
                    n += 1
                    if "map_provenance" in cols:
                        pv = str(row.get("map_provenance", "")).strip() or "UNSPECIFIED"
                        counts[pv] = counts.get(pv, 0) + 1
            rec.update({
                "rows": n,
                "columns": cols,
                "provenance_counts": counts or None,
                "has_fallback_provenance": "fallback_resolution" in cols,
            })
        except Exception as e:
            rec["error"] = str(e)
        return rec

    def list_maps(self) -> List[Dict[str, Any]]:
        return [{"key": k, "family": map_family(k)} for k in map_inventory()]

    # -- capabilities (from installed native source maps; no runtime load) ---

    def capabilities(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.registry.is_installed(key):
            return None
        with self._cap_lock:
            if key in self._capabilities:
                return self._capabilities[key]
        if key in self.registry.loaded:
            possible = self.registry.loaded[key].possible
        else:
            names, values = _read_native_columns(model_dir(key))
            possible = {names[i]: list(values.get(i, [])) for i in range(len(names))}
        feat = set(possible)
        country_feats = sorted(
            [v for v in feat if "country" in v.lower() and "region" not in v.lower() and possible.get(v)],
            key=localized._country_feature_priority,
        )
        cap = {
            "features": len(feat),
            "country_features": country_feats,
            "country_values": list(possible.get(country_feats[0], [])) if country_feats else [],
            "coordinate_features": [v for v in ("O1_LONGITUDE", "O2_LATITUDE") if v in feat],
            "year_feature": "A_YEAR" if "A_YEAR" in feat else None,
            "year_values": sorted(possible.get("A_YEAR", [])),
        }
        cap["geography_mode"] = (
            "categorical_country" if country_feats else
            "coordinates" if len(cap["coordinate_features"]) == 2 else
            "survey_context_only"
        )
        with self._cap_lock:
            self._capabilities[key] = cap
        return cap

    def preview_conditioning(self, key: str, country: str, continent: str, year: Optional[int]) -> Optional[Dict[str, Any]]:
        """Run the real forced-assignment logic against the model's support."""
        if not self.registry.is_installed(key):
            return None
        if key in self.registry.loaded:
            possible = self.registry.loaded[key].possible
        else:
            names, values = _read_native_columns(model_dir(key))
            possible = {names[i]: list(values.get(i, [])) for i in range(len(names))}
        try:
            forced, meta = localized.build_forced_assignments(
                feat=set(possible), possible=possible, year=year, country=country, continent=continent,
            )
        except ValueError as e:
            return {"error": str(e)}
        return {"forced": dict(forced), "meta": meta}

    # -- profiles ------------------------------------------------------------

    def configured_profile_models(self) -> Dict[str, str]:
        out = {}
        models = self.cfg.get("models", {}) or {}
        for name, spec in (self.cfg.get("interactive_profiles", {}) or {}).items():
            ref = str((spec or {}).get("qnet", ""))
            k = model_key_from_path(str(models.get(ref, ref)))
            if k:
                out[str(name)] = k
        return out

    def _configured_spec(self, name: str) -> ProfileSpec:
        try:
            r = interactive.resolve_profile(self.cfg, name, self.config_root)
        except SystemExit as e:
            raise DTAGEngineError(str(e))
        key = model_key_from_path(r["qnet"])
        if not key:
            raise DTAGEngineError(f"Profile {name!r} model path is not a DTAG model key: {r['qnet']}")
        try:
            map_key = Path(r["map_path"]).resolve().relative_to(maps_root().resolve()).as_posix()
        except ValueError:
            raise DTAGEngineError(f"Profile {name!r} map is outside the map inventory: {r['map']}")
        polar_set = _polar_set_for_path(r["polar_vectors"])
        run = r["run"]
        run_params = {k: run[k] for k in list(RUN_PARAM_BOUNDS) + list(RUN_PARAM_CHOICES) if k in run and run[k] is not None}
        for k in SERVER_RUN_PARAMS:
            if run.get(k):
                run_params[k] = run[k]
        run_params["timing"] = True
        if run.get("require_polar_vectors"):
            run_params["require_polar_vectors"] = True
        year = r["year"]
        return ProfileSpec(
            name=name,
            source="configured",
            description=r["description"],
            family=family_of(key),
            model_key=key,
            map_key=map_key,
            persona=r["persona"],
            country=r["country"] or "",
            continent=r["continent"] or "",
            year=int(year) if year not in (None, "") else None,
            polar_set=polar_set,
            ideology=bool(polar_set) and not bool(run.get("no_ideology")),
            run=run_params,
        )

    def _custom_spec(self, name: str, data: Dict[str, Any]) -> ProfileSpec:
        base = data.get("base_profile")
        if base and base in (self.cfg.get("interactive_profiles") or {}):
            spec = self._configured_spec(base)
        else:
            mk = self.validate_model_key(str(data.get("model_key", "")))
            spec = self._adhoc_spec(mk)
        spec.name = name
        spec.source = "custom"
        spec.base_profile = base
        spec.description = str(data.get("description", "") or spec.description)
        overrides = {k: data[k] for k in OVERRIDE_FIELDS if k in data}
        return self.apply_overrides(spec, overrides)

    def _adhoc_spec(self, model_key: str) -> ProfileSpec:
        fam = family_of(model_key)
        map_key = canonical_map_key(model_key)
        if not map_key:
            raise DTAGEngineError(f"No semantic map in the repository for model {model_key}")
        defaults_run = dict((self.cfg.get("defaults", {}) or {}).get("run", {}) or {})
        if fam == "eurobarometer":
            run = dict(ebnative.EUROBAROMETER_RUN_DEFAULTS)
            persona = ebnative.DEFAULT_PERSONA
            continent = ebnative.DEFAULT_CONTINENT
        else:
            run = {k: defaults_run[k] for k in list(RUN_PARAM_BOUNDS) + list(RUN_PARAM_CHOICES) if k in defaults_run}
            run["resp_mode"] = "max"
            if "seed_base" in defaults_run:
                run.setdefault("seed", defaults_run["seed_base"])
            for k in SERVER_RUN_PARAMS:
                if defaults_run.get(k):
                    run[k] = defaults_run[k]
            persona = ""
            continent = ""
        run.pop("no_ideology", None)
        run["timing"] = True
        polar_sets = [k for k, v in POLAR_VECTOR_SETS.items() if fam in v["families"]]
        spec = ProfileSpec(
            name=f"adhoc:{model_key}",
            source="adhoc",
            description=f"{model_label(model_key)} (ad hoc)",
            family=fam,
            model_key=model_key,
            map_key=map_key,
            persona=persona,
            continent=continent,
            year=model_year(model_key),
            za=za_of_model(model_key),
            polar_set=polar_sets[0] if polar_sets else None,
            ideology=bool(polar_sets),
            run=run,
        )
        if fam == "gss":
            spec.country = "United States"
        return spec

    def list_profiles(self) -> List[Dict[str, Any]]:
        out = []
        for name in sorted((self.cfg.get("interactive_profiles") or {})):
            try:
                spec = self._configured_spec(name)
                out.append(self._profile_listing(spec))
            except DTAGEngineError as e:
                out.append({"name": name, "source": "configured", "error": str(e)})
        for name, data in sorted(self.profile_store.load().items()):
            try:
                spec = self._custom_spec(name, data)
                out.append(self._profile_listing(spec))
            except DTAGEngineError as e:
                out.append({"name": name, "source": "custom", "error": str(e)})
        return out

    def _profile_listing(self, spec: ProfileSpec) -> Dict[str, Any]:
        d = spec.as_dict()
        st = self.registry.status(spec.model_key)
        d["model_status"] = st.state
        d["model_installed"] = self.registry.is_installed(spec.model_key)
        d["model_loaded"] = spec.model_key in self.registry.loaded
        d["allowed_overrides"] = list(OVERRIDE_FIELDS)
        return d

    def get_profile(self, name: str) -> ProfileSpec:
        if name in (self.cfg.get("interactive_profiles") or {}):
            return self._configured_spec(name)
        custom = self.profile_store.load()
        if name in custom:
            return self._custom_spec(name, custom[name])
        raise DTAGEngineError(f"Unknown profile {name!r}")

    def apply_overrides(self, spec: ProfileSpec, overrides: Optional[Dict[str, Any]]) -> ProfileSpec:
        """Validate browser/API overrides and return a new resolved spec."""
        spec = ProfileSpec(**{**spec.__dict__, "run": dict(spec.run), "warnings": [], "temporal": {}})
        ov = dict(overrides or {})
        unknown = sorted(set(ov) - set(OVERRIDE_FIELDS))
        if unknown:
            raise DTAGEngineError(f"Unsupported override field(s): {unknown}")

        if "persona" in ov and ov["persona"] is not None:
            spec.persona = _clean_text("persona", ov["persona"], 4000)
        for f in ("country", "continent"):
            if f in ov and ov[f] is not None:
                setattr(spec, f, _clean_text(f, ov[f], 120))
        for k in list(RUN_PARAM_BOUNDS) + list(RUN_PARAM_CHOICES):
            if k in ov and ov[k] is not None and ov[k] != "":
                spec.run[k] = _coerce_param(k, ov[k])

        if "model_key" in ov and ov["model_key"]:
            mk = self.validate_model_key(str(ov["model_key"]))
            if mk != spec.model_key:
                spec.model_key = mk
                spec.family = family_of(mk)
                spec.map_key = canonical_map_key(mk) or ""
                spec.za = za_of_model(mk)
                if spec.family == "gss":
                    spec.year = model_year(mk)

        if "year" in ov:
            y = ov["year"]
            if y in (None, ""):
                spec.year = None
            else:
                try:
                    spec.year = int(y)
                except Exception:
                    raise DTAGEngineError("year must be an integer")
                if not (1900 <= spec.year <= 2100):
                    raise DTAGEngineError("year must be within [1900, 2100]")

        # WHEN: family-specific time semantics.
        if spec.family == "gss" and spec.year is not None and model_year(spec.model_key) != spec.year:
            target = f"gss/gss_{spec.year}"
            if target not in set(self.catalog_keys()):
                years = sorted(y for y in (model_year(k) for k in self.catalog_keys()) if y)
                raise DTAGEngineError(
                    f"No native GSS wave model for {spec.year}. Available GSS waves: {years}"
                )
            spec.model_key = target
            spec.map_key = canonical_map_key(target) or ""

        if spec.family == "eurobarometer":
            self._route_eurobarometer(spec, ov)

        if "map_key" in ov and ov["map_key"]:
            mk = self.validate_map_key(str(ov["map_key"]))
            fam = map_family(mk)
            if fam and fam != spec.family:
                raise DTAGEngineError(f"Map {mk} belongs to {fam}, not {spec.family}")
            spec.map_key = mk
            if mk != canonical_map_key(spec.model_key):
                spec.warnings.append(
                    f"Map {mk} is not the canonical map for {spec.model_key}; only overlapping variables are used."
                )
        if not spec.map_key:
            raise DTAGEngineError(f"No semantic map available for {spec.model_key}")
        self.validate_map_key(spec.map_key)

        # Ideology: only registered, family-compatible polar vectors.
        if "polar_set" in ov:
            ps = ov["polar_set"]
            spec.polar_set = str(ps) if ps else None
        if spec.polar_set is not None:
            if spec.polar_set not in POLAR_VECTOR_SETS:
                raise DTAGEngineError(f"Unknown polar-vector set {spec.polar_set!r}")
            if spec.family not in POLAR_VECTOR_SETS[spec.polar_set]["families"]:
                raise DTAGEngineError(
                    f"Polar-vector set {spec.polar_set!r} is registered for "
                    f"{POLAR_VECTOR_SETS[spec.polar_set]['families']} only, not {spec.family}."
                )
        if "ideology" in ov and ov["ideology"] is not None:
            spec.ideology = bool(ov["ideology"])
        if spec.ideology and spec.polar_set is None:
            compat = [k for k, v in POLAR_VECTOR_SETS.items() if spec.family in v["families"]]
            if compat:
                spec.polar_set = compat[0]
            else:
                spec.ideology = False
                spec.warnings.append("Polar vectors are unavailable for this survey/model; ideology is disabled.")
        if not spec.ideology:
            spec.run.pop("require_polar_vectors", None)

        if not spec.persona.strip():
            raise DTAGEngineError("persona must be non-empty")

        spec.temporal = self._temporal_plan(spec)
        spec.warnings.extend(self._conditioning_warnings(spec))
        return spec

    def _route_eurobarometer(self, spec: ProfileSpec, ov: Dict[str, Any]) -> None:
        router = self.eurobarometer
        if ov.get("za"):
            za = normalize_za(str(ov["za"]))
            spec.za = za
            spec.date = None
            spec.model_key = self._eb_model_for_za(za)
            spec.map_key = canonical_map_key(spec.model_key) or ""
            spec.temporal = {"selection": "explicit_za"}
            return
        if ov.get("date"):
            try:
                when = date.fromisoformat(str(ov["date"]))
            except ValueError:
                raise DTAGEngineError("date must use YYYY-MM-DD")
            wave = router.resolve_date(when)
            spec.date = when.isoformat()
            spec.za = wave.za_id
            spec.model_key = self._eb_model_for_za(wave.za_id)
            spec.map_key = canonical_map_key(spec.model_key) or ""
            return
        if "year" in ov and ov["year"] not in (None, "") and not ov.get("model_key"):
            if not router.available():
                raise DTAGEngineError(
                    "A year alone cannot select a Eurobarometer wave and no fieldwork-date "
                    "registry is available; choose an explicit ZA."
                )
            waves = router.waves_in_year(int(ov["year"]))
            ids = [w.za_id for w in waves]
            if len(ids) == 1:
                raise DTAGEngineError(
                    f"The requested year {ov['year']} overlaps one Eurobarometer wave ({ids[0]}); "
                    "confirm it by choosing a survey date or the explicit ZA."
                )
            raise DTAGEngineError(
                f"The requested year {ov['year']} is ambiguous for Eurobarometer "
                f"({len(ids)} fieldwork waves: {', '.join(ids[:12])}{' ...' if len(ids) > 12 else ''}); "
                "choose a survey date or an explicit ZA."
            )

    def _eb_model_for_za(self, za: str) -> str:
        hits = [k for k in self.catalog_keys() if za_of_model(k) == za]
        if not hits:
            raise DTAGEngineError(f"{za} has no native DTAG model in the catalog.")
        if len(hits) > 1:
            raise DTAGEngineError(f"Multiple native models match {za}: {hits}; choose model_key explicitly.")
        return hits[0]

    def _temporal_plan(self, spec: ProfileSpec) -> Dict[str, Any]:
        fam = spec.family
        if fam == "gss":
            return {
                "family": fam,
                "mode": "wave_model_selection",
                "requested_year": spec.year,
                "selected_model": spec.model_key,
                "wave": model_label(spec.model_key),
            }
        if fam == "wvs":
            return {
                "family": fam,
                "mode": "pooled_model_year_feature",
                "requested_year": spec.year,
                "selected_model": spec.model_key,
                "wave": model_label(spec.model_key),
            }
        if fam == "afrobarometer":
            return {
                "family": fam,
                "mode": "round_model_selection",
                "requested_year": spec.year,
                "selected_model": spec.model_key,
                "wave": model_label(spec.model_key),
            }
        if fam == "eurobarometer":
            w = self.eurobarometer.wave_for_za(spec.za) if (spec.za and self.eurobarometer.available()) else None
            return {
                "family": fam,
                "mode": "fieldwork_date_routing" if spec.date else "explicit_za",
                "requested_date": spec.date,
                "requested_year": spec.year,
                "resolved_za": spec.za,
                "fieldwork": EurobarometerRouter.wave_dict(w) if w else None,
                "date_registry_available": self.eurobarometer.available(),
                "selected_model": spec.model_key,
                "wave": model_label(spec.model_key),
            }
        return {"family": fam, "selected_model": spec.model_key}

    def _conditioning_warnings(self, spec: ProfileSpec) -> List[str]:
        warns: List[str] = []
        if spec.family == "eurobarometer" and spec.za:
            src = "date" if spec.date else "explicit ZA"
            warns.append(f"The requested {src} resolves to Eurobarometer {spec.za} ({spec.model_key}).")
            mr = self.map_record(spec.map_key)
            if mr.get("has_fallback_provenance"):
                warns.append(
                    f"Semantic map {spec.map_key} uses semantic-union fallback documentation "
                    "(not exact wave-specific documentation) for some rows."
                )
        if not spec.ideology or spec.polar_set is None:
            if not any(spec.family in v["families"] for v in POLAR_VECTOR_SETS.values()):
                warns.append("Polar vectors are unavailable for this survey/model.")
        prev = self.preview_conditioning(spec.model_key, spec.country, spec.continent, spec.year)
        cap = self.capabilities(spec.model_key)
        if prev is None or cap is None:
            if spec.country:
                warns.append("Model not installed yet; geographic conditioning is determined when it is installed.")
            return warns
        if "error" in prev:
            warns.append(f"Geography: {prev['error']}")
            return warns
        meta = prev["meta"]
        mode = meta.get("geography_conditioning_mode")
        if spec.country or spec.continent:
            if mode == "categorical_country":
                warns.append(
                    f"Country is hard-conditioned through {meta.get('categorical_country_feature')}="
                    f"{meta.get('categorical_country_value')!r}."
                )
            elif "O1_LONGITUDE" in prev["forced"]:
                warns.append("This model uses coordinate localization rather than a categorical country feature.")
            else:
                warns.append("Country is contextual only for this model.")
        for k in ("year_warning", "geography_warning", "country_warning"):
            if not meta.get(k):
                continue
            if k == "year_warning" and spec.family == "gss":
                continue  # GSS time is wave-model selection, not a year variable
            if k == "geography_warning" and mode not in ("categorical_country",) and "O1_LONGITUDE" not in prev["forced"]:
                continue  # already summarised as "Country is contextual only"
            warns.append(str(meta[k]))
        return warns

    def build_spec(self, profile: Optional[str] = None, overrides: Optional[Dict[str, Any]] = None, model_key: Optional[str] = None) -> ProfileSpec:
        if profile:
            base = self.get_profile(profile)
        elif model_key:
            base = self._adhoc_spec(self.validate_model_key(model_key))
        elif overrides and overrides.get("model_key"):
            base = self._adhoc_spec(self.validate_model_key(str(overrides["model_key"])))
        else:
            raise DTAGEngineError("Provide a profile name or a model_key.")
        return self.apply_overrides(base, overrides)

    def save_profile(self, name: str, spec: ProfileSpec) -> ProfileSpec:
        if not PROFILE_NAME_RE.fullmatch(name):
            raise DTAGEngineError("Profile name must be 1-64 characters of letters, digits, '_', '-', '.'")
        if name in (self.cfg.get("interactive_profiles") or {}):
            raise DTAGEngineError(f"{name!r} is a configured profile; choose another name.")
        data = spec.storable()
        data["name"] = name
        self.profile_store.save(name, data)
        return self.get_profile(name)

    # -- sessions --------------------------------------------------------------

    def session_config(self, spec: ProfileSpec) -> SessionConfig:
        run = dict(spec.run)
        cfg = SessionConfig()
        for k, v in run.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        if self.openai_model_override:
            cfg.openai_model = self.openai_model_override
        cfg.year = spec.year
        cfg.country = spec.country
        cfg.continent = spec.continent
        cfg.no_ideology = not spec.ideology
        cfg.require_polar_vectors = bool(run.get("require_polar_vectors")) and spec.ideology
        cfg.timing = True
        return cfg

    def create_session(
        self,
        profile: Optional[str] = None,
        overrides: Optional[Dict[str, Any]] = None,
        spec: Optional[ProfileSpec] = None,
        model_key: Optional[str] = None,
    ) -> EngineSession:
        if spec is None:
            spec = self.build_spec(profile=profile, overrides=overrides, model_key=model_key)
        if not self.llm_ready:
            raise DTAGEngineError(
                "OPENAI_API_KEY is not configured on the server; DTAG needs it for persona "
                "interpretation, variable selection and answer rendering."
            )
        timings: Dict[str, float] = {}
        t0 = time.time()
        was_loaded = spec.model_key in self.registry.loaded
        lm = self.registry.load(spec.model_key)
        timings["model_ready"] = time.time() - t0
        timings["model_was_resident"] = 1.0 if was_loaded else 0.0

        map_path = map_inventory()[spec.map_key]
        t1 = time.time()
        try:
            ctx = lm.context(map_path)
        except DTAGConfigError as e:
            raise DTAGEngineError(str(e))
        timings["context"] = time.time() - t1

        config = self.session_config(spec)
        if spec.ideology and spec.polar_set:
            polar = lm.polar(ctx, str(REPO_ROOT / POLAR_VECTOR_SETS[spec.polar_set]["path"]))
        else:
            polar = PolarGeometry(disable_reason="Ideology trajectory is not available for this survey/profile.")
        try:
            sess = DTAGSession(
                ctx=ctx,
                persona=spec.persona,
                config=config,
                polar=polar,
                client_factory=self.client_factory,
                forced_assignment_fn=localized.build_forced_assignments,
                timings_init={"load_polar_vectors": polar.seconds},
            )
        except DTAGConfigError as e:
            raise DTAGEngineError(str(e))
        timings.update(sess.timings_init)
        timings["total"] = time.time() - t0
        return EngineSession(self, spec, sess, lm, {
            "timings": timings,
            "llm": self.llm_info(config.openai_model),
        })

    # -- conditioning metadata --------------------------------------------------

    def geographic_conditioning(self, spec: ProfileSpec, sess: DTAGSession) -> Dict[str, Any]:
        meta = sess.geo_meta
        forced = sess.forced_assignments
        geo_vars = {k: v for k, v in forced.items() if k != "A_YEAR"}
        raw_mode = meta.get("geography_conditioning_mode")
        if raw_mode == "categorical_country":
            mode = "categorical_country"
        elif "O1_LONGITUDE" in geo_vars:
            mode = "coordinates"
        elif spec.country or spec.continent:
            mode = "survey_context_only"
        else:
            mode = "none"
        out = {
            "requested_country": spec.country or None,
            "requested_continent": spec.continent or None,
            "resolved_country": meta.get("categorical_country_value") or meta.get("resolved_country_key"),
            "resolved_continent": meta.get("resolved_continent_key"),
            "conditioning_mode": mode,
            "conditioned_variables": geo_vars,
            "target_coordinates": (
                {"longitude": meta.get("target_longitude"), "latitude": meta.get("target_latitude")}
                if mode == "coordinates" else None
            ),
            "context_text": {
                "country": bool(spec.country), "continent": bool(spec.continent),
                "note": "Country/continent are also added to the persona text given to the LLM; only conditioned_variables constrain the native LSM.",
            },
            "warnings": [str(meta[k]) for k in ("geography_warning", "country_warning") if meta.get(k)],
        }
        return out

    def temporal_conditioning(self, spec: ProfileSpec, sess: DTAGSession) -> Dict[str, Any]:
        t = dict(spec.temporal or self._temporal_plan(spec))
        forced = sess.forced_assignments
        t["conditioned_variables"] = {"A_YEAR": forced["A_YEAR"]} if "A_YEAR" in forced else {}
        meta = sess.geo_meta
        t["warnings"] = [str(meta["year_warning"])] if meta.get("year_warning") and spec.family != "gss" else []
        if spec.family == "gss":
            t["note"] = "Time selects the GSS survey-wave model; no year variable is hard-conditioned."
        elif spec.family == "wvs":
            t["note"] = "Pooled WVS7 model; year is hard-conditioned through A_YEAR when supported."
        elif spec.family == "eurobarometer":
            t["note"] = "A date selects one discrete Eurobarometer wave; no interpolation between waves."
        return t

    # -- export -----------------------------------------------------------------

    def export_session(self, es: EngineSession) -> Dict[str, Any]:
        s = es.session
        mrec = es.model_info()
        return {
            "export_schema": "dtag-session-export/1",
            "exported_at": _now(),
            "dtag": {
                "version": dtag_version(),
                "git_commit": git_commit(),
                "native_runtime": getattr(es.loaded.backend, "runtime_kind", None),
            },
            "session_id": es.id,
            "created_at": es.created_at,
            "profile": es.spec.as_dict(),
            "model": {
                "key": es.spec.model_key,
                "release": mrec.get("release"),
                "sha256": mrec.get("sha256"),
                "archive": mrec.get("archive"),
                "archive_bytes": mrec.get("archive_bytes"),
                "features": len(es.loaded.backend.feature_names),
                "usable_trees": len(es.loaded.backend.usable_tree_ids),
            },
            "map": self.map_record(es.spec.map_key),
            "persona": {"base": s.persona_base, "full_text": s.persona},
            "geography": {"requested": {"country": es.spec.country, "continent": es.spec.continent},
                          "resolved": es.geographic_conditioning},
            "time": {"requested": {"year": es.spec.year, "date": es.spec.date, "za": es.spec.za},
                     "resolved": es.temporal_conditioning},
            "config": s.config.to_dict(),
            "random_seed": s.config.seed,
            "response_mode": s.config.resp_mode,
            "semantic_fallback": s.config.semantic_fallback,
            "llm": es.init_info.get("llm"),
            "initialization": s.snapshot(),
            "init_timings": es.init_info.get("timings", {}),
            "ideology": es.ideology_summary(),
            "questions": [EngineSession._history_item(r) for r in s.results],
            "records_cli_schema": list(s.records),
            "final_state": dict(s.state),
        }

    def export_csv(self, es: EngineSession) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "session_id", "model_key", "map_key", "profile", "seed", "resp_mode", "semantic_fallback",
            "query_idx", "question", "mapping", "state_changed", "selected_variables", "anchors",
            "state_updates", "ideology_before", "ideology_after", "ideology_delta",
            "semantic_trigger", "skip_reason", "answer", "timing_total_s", "timing_native_predict_s",
        ])
        s = es.session
        for r in s.results:
            t = r["timings"]
            w.writerow([
                es.id, es.spec.model_key, es.spec.map_key, es.spec.name, s.config.seed, s.config.resp_mode,
                s.config.semantic_fallback, r["query_idx"], r["question"], r["mapping"]["label"],
                r["state_changed"], ";".join(r["selected_variables"]),
                json.dumps({a["variable"]: a["response"] for a in r["anchors"]}, ensure_ascii=False),
                json.dumps(r["state_updates"], ensure_ascii=False),
                r["ideology"]["before"], r["ideology"]["after"], r["ideology"]["delta"],
                r["mapping"]["semantic_trigger"] or "", r["mapping"]["skip_reason"] or "", r["answer"],
                round(t.get("total", 0.0), 4),
                round(t.get("native_predict", t.get("semantic_native_predict", 0.0)), 6),
            ])
        return buf.getvalue()

    # -- readiness -----------------------------------------------------------------

    def readiness(self) -> Dict[str, Any]:
        try:
            sys_path_ok = True
            from model_backend import _add_lsm_bindings_dir
            _add_lsm_bindings_dir()
            import dtag_lsm  # noqa: F401
            native = {"available": True, "runtime": "bundled_persistent", "module": getattr(dtag_lsm, "__file__", None) and Path(dtag_lsm.__file__).name}
        except Exception as e:
            sys_path_ok = False
            native = {"available": False, "error": str(e), "fix": "bash scripts/build_native_bindings.sh"}
        inv = map_inventory()
        fam_maps: Dict[str, int] = {}
        for k in inv:
            f = map_family(k) or "other"
            fam_maps[f] = fam_maps.get(f, 0) + 1
        manifest = self.manifest.get()
        man_models = sorted((manifest or {}).get("models", {}))
        fam_models: Dict[str, int] = {}
        for k in man_models:
            fam_models[family_of(k)] = fam_models.get(family_of(k), 0) + 1
        missing_maps = [k for k in man_models if canonical_map_key(k) is None]
        installed = self.installed_keys()
        profiles = sorted((self.cfg.get("interactive_profiles") or {}))
        eb_waves = self.eurobarometer.waves() if self.eurobarometer.available() else []
        ready = bool(native["available"]) and bool(manifest) and not missing_maps and self.llm_ready
        return {
            "status": "ready" if ready else "degraded",
            "checked_at": _now(),
            "dtag_version": dtag_version(),
            "native_runtime": native,
            "public_catalog": {
                "reachable": manifest is not None,
                "error": self.manifest.error,
                "release": (manifest or {}).get("release", self.manifest.release),
                "manifest_url": self.manifest.url,
                "models": len(man_models),
                "by_family": fam_models,
                "total_archive_bytes": (manifest or {}).get("total_archive_bytes"),
            },
            "semantic_maps": {
                "maps": len(inv),
                "matched_to_catalog": len(man_models) - len(missing_maps),
                "by_family": fam_maps,
                "catalog_models_missing_map": missing_maps,
            },
            "model_cache": {"root": str(dtag_paths.model_root()), "installed": len(installed), "installed_keys": installed},
            "models_resident": {"loaded": len(self.registry.loaded), "keys": sorted(self.registry.loaded)},
            "configured_profiles": {"count": len(profiles), "names": profiles},
            "eurobarometer_dates": {
                "available": self.eurobarometer.available(),
                "registry": self.eurobarometer.registry_path().name if self.eurobarometer.available() else None,
                "waves": len(eb_waves),
            },
            "llm": {
                "backend": self.llm_backend,
                "openai_configured": self.openai_configured,
                "ready": self.llm_ready,
                "default_openai_model": self.openai_model_override or ((self.cfg.get("defaults") or {}).get("run") or {}).get("openai_model"),
            },
            "_ok": sys_path_ok,
        }
