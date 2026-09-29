#!/usr/bin/env python3
"""Shared filesystem resolution for native-only DTAG.

DTAG source code, maps, and manifests live in the Git checkout. Native LSM
models may either live under <repo>/models/lsm or in an external model store.

Set:

    export DTAG_MODEL_ROOT=/path/to/native/models

The external root must contain the family directories directly:

    $DTAG_MODEL_ROOT/
      gss/
      afrobarometer/
      wvs/
      eurobarometer/
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_installed_models(root: Path) -> bool:
    for family in ("gss", "afrobarometer", "wvs", "eurobarometer"):
        p = root / family
        if p.is_dir() and any(x.is_dir() for x in p.iterdir()):
            return True
    return False


def model_root(repo_root: Path = REPO_ROOT) -> Path:
    value = str(os.environ.get("DTAG_MODEL_ROOT", "")).strip()
    if value:
        return Path(value).expanduser().resolve()

    # Preserve an existing developer checkout that already contains models.
    local = (repo_root / "models" / "lsm").resolve()
    if _has_installed_models(local):
        return local

    # Fresh clones / pip-style installs use a per-user cache outside Git.
    return (Path.home() / ".cache" / "dtag" / "models").resolve()


def resolve_repo_path(value: str | Path, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve a normal repository path, redirecting models/lsm through DTAG_MODEL_ROOT."""
    p = Path(value).expanduser()
    if p.is_absolute():
        return p.resolve()

    parts = p.parts
    if len(parts) >= 2 and parts[0] == "models" and parts[1] == "lsm":
        tail = Path(*parts[2:]) if len(parts) > 2 else Path()
        return (model_root(repo_root) / tail).resolve()

    return (repo_root / p).resolve()


def model_path(*parts: str, repo_root: Path = REPO_ROOT) -> Path:
    return model_root(repo_root).joinpath(*parts).resolve()
