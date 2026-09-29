"""Shared fixtures for the DTAG web/engine test suite.

Two tiers:

* fast tests use a tiny deterministic ``FakeBackend`` standing in for the
  native runtime, so API schemas and engine validation run anywhere;
* ``native`` tests use a real downloaded native LSM model (GSS 2024 by
  default). They use ``DTAG_MODEL_ROOT`` when it already holds the model,
  otherwise download it once from the public release into a session-scoped
  cache. Set ``DTAG_TEST_OFFLINE=1`` to skip them.

The language layer is always the deterministic mock (no OPENAI_API_KEY).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "webapp" / "backend"))
os.environ["DTAG_LLM_BACKEND"] = "mock"
os.environ.setdefault("DTAG_WEB_NO_AUTOAPP", "1")

NATIVE_KEY = os.environ.get("DTAG_TEST_NATIVE_MODEL", "gss/gss_2024")


# -----------------------------
# Fake native backend (fast tier)
# -----------------------------

FAKE_SUPPORT: Dict[str, List[str]] = {
    "year": ["2024"],
    "sex": ["male", "female"],
    "polviews": ["extremely liberal", "liberal", "moderate", "conservative", "extremely conservative"],
    "immassim": ["very important", "fairly important", "not very important", "not important at all"],
    "abany": ["yes", "no"],
    "attend": ["never", "once a year", "every week"],
    "natenvir": ["too little", "about right", "too much"],
    "gunlaw": ["favor", "oppose"],
}


class FakeBackend:
    """Deterministic stand-in with the NativeLSMBackend interface."""

    backend_name = "native_lsm"
    runtime_kind = "fake_for_tests"

    def __init__(self, path):
        self.path = str(path)
        self.feature_names = list(FAKE_SUPPORT)
        self.usable_tree_ids = list(range(len(self.feature_names)))
        self.predict_calls = 0

    def possible_values(self):
        return {k: list(v) for k, v in FAKE_SUPPORT.items()}

    def cache_signature(self):
        return f"fake|{self.path}"

    def predict_distributions(self, row: Sequence[str], target_names: Optional[Sequence[str]] = None):
        self.predict_calls += 1
        ctx = "|".join(str(x) for x in row)
        out = {}
        for name in (target_names or self.feature_names):
            if name not in FAKE_SUPPORT:
                continue
            vals = FAKE_SUPPORT[name]
            w = np.array([int(hashlib.md5(f"{ctx}#{name}#{v}".encode()).hexdigest()[:6], 16) + 1 for v in vals], float)
            w = w / w.sum()
            out[name] = {v: float(p) for v, p in zip(vals, w)}
        return out

    def qdistance(self, a, b):
        return float(sum(1 for x, y in zip(a, b) if str(x) != str(y))) + 0.5

    def distances_to_state(self, left, right, state):
        return self.qdistance(left, state), self.qdistance(right, state)


@pytest.fixture()
def fake_model_root(tmp_path, monkeypatch):
    root = tmp_path / "models"
    d = root / "gss" / "gss_2024"
    (d / "source_maps").mkdir(parents=True)
    (d / "trees" / "binary").mkdir(parents=True)
    monkeypatch.setenv("DTAG_MODEL_ROOT", str(root))
    return root


@pytest.fixture()
def fake_engine(fake_model_root, tmp_path):
    from dtag_engine import DTAGEngine

    loads: List[str] = []

    def loader(path):
        loads.append(str(path))
        return FakeBackend(path)

    eng = DTAGEngine(
        assets_dir=tmp_path / "assets",
        profiles_path=tmp_path / "profiles.json",
        llm_backend="mock",
        model_loader=loader,
    )
    eng.manifest.set(fake_manifest())
    eng._test_loads = loads  # type: ignore[attr-defined]
    return eng


def fake_manifest(extra: Optional[Dict[str, dict]] = None) -> dict:
    models = {
        "gss/gss_2024": {"archive": "gss/gss_2024.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
        "gss/gss_2022": {"archive": "gss/gss_2022.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
        "wvs/wvs7_pooled": {"archive": "wvs/wvs7_pooled.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
        "afrobarometer/r5": {"archive": "afrobarometer/r5.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
        "eurobarometer/ZA7575_v1-0-0": {"archive": "eurobarometer/ZA7575_v1-0-0.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
        "eurobarometer/ZA7576_v1-0-0": {"archive": "eurobarometer/ZA7576_v1-0-0.tar.zst", "sha256": "0" * 64, "size_bytes": 1},
    }
    models.update(extra or {})
    return {"release": "vTEST", "base_url": "file:///nonexistent", "models": models}


@pytest.fixture()
def fake_client(fake_engine):
    from fastapi.testclient import TestClient
    from dtag_web.app import create_app

    app = create_app(engine=fake_engine, frontend_dist=Path("/nonexistent"))
    return TestClient(app)


# -----------------------------
# Real native model (integration tier)
# -----------------------------

def _installed(root: Path, key: str) -> bool:
    return (root / key / "source_maps").is_dir() and (root / key / "trees" / "binary").is_dir()


@pytest.fixture(scope="session")
def native_model_root(tmp_path_factory) -> Path:
    if os.environ.get("DTAG_TEST_OFFLINE") == "1":
        pytest.skip("DTAG_TEST_OFFLINE=1")
    try:
        from model_backend import _add_lsm_bindings_dir
        _add_lsm_bindings_dir()
        import dtag_lsm  # noqa: F401
    except Exception as e:
        pytest.skip(f"native dtag_lsm extension unavailable: {e}")
    env = os.environ.get("DTAG_MODEL_ROOT", "").strip()
    if env and _installed(Path(env), NATIVE_KEY):
        return Path(env).resolve()
    import fetch_models

    root = tmp_path_factory.mktemp("dtag-native-models")
    try:
        manifest = fetch_models.load_manifest(timeout=30)
        fetch_models.fetch_one(root, manifest, NATIVE_KEY, log=lambda *_: None)
    except Exception as e:
        pytest.skip(f"cannot obtain native model {NATIVE_KEY}: {e}")
    return root


@pytest.fixture(scope="session")
def native_engine(native_model_root, tmp_path_factory):
    """One engine (one process-level model cache) for all native tests."""
    os.environ["DTAG_MODEL_ROOT"] = str(native_model_root)
    from dtag_engine import DTAGEngine

    tmp = tmp_path_factory.mktemp("dtag-native-engine")
    return DTAGEngine(assets_dir=tmp / "assets", profiles_path=tmp / "profiles.json", llm_backend="mock")
