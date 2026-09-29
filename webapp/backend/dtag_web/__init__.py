"""DTAG web application (FastAPI) around the native DTAG engine.

The scientific implementation lives in the DTAG ``scripts/`` tree
(``dtag_engine`` / ``dtag_session`` / ``pipeline``); this package only
exposes it over HTTP and serves the browser UI.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def dtag_root() -> Path:
    override = os.environ.get("DTAG_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # <root>/webapp/backend/dtag_web/__init__.py
    return Path(__file__).resolve().parents[3]


DTAG_ROOT = dtag_root()
_SCRIPTS = str(DTAG_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

__all__ = ["DTAG_ROOT", "dtag_root"]
