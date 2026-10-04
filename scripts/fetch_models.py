#!/usr/bin/env python3
"""Fetch public DTAG native models into the local model cache.

Reusable functions (used by ``dtag-models`` and the DTAG web application):

* ``load_manifest(release)``     -- public release manifest (JSON)
* ``installed(root, key)``       -- native model directory present and valid
* ``fetch_one(root, manifest, key, progress=...)``
      download .tar.zst -> SHA256 verify -> safe extract -> validate -> install

The model root is resolved by ``dtag_paths.model_root()`` so the downloader and
the runtime always agree on where models live.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

import zstandard as zstd

from dtag_paths import model_root

DEFAULT_RELEASE = os.environ.get("DTAG_MODEL_RELEASE", "v0.2.1")
DEFAULT_BUCKET = os.environ.get(
    "DTAG_PUBLIC_BUCKET", "git-zeroknowledgediscovery-dtag"
)

MODEL_KEY_RE = re.compile(r"^(gss|afrobarometer|wvs|eurobarometer)/[A-Za-z0-9._-]+$")

# progress(stage, done_bytes, total_bytes); stage in
# downloading | verifying | extracting | installed
ProgressFn = Callable[[str, int, int], None]


def default_root() -> Path:
    return model_root()


def manifest_url(release: str = DEFAULT_RELEASE) -> str:
    override = os.environ.get("DTAG_MODEL_MANIFEST_URL", "").strip()
    if override:
        return override
    return (
        f"https://storage.googleapis.com/{DEFAULT_BUCKET}/"
        f"models/{release}/manifest.json"
    )


def load_manifest(release: str = DEFAULT_RELEASE, timeout: float = 60) -> dict:
    with urllib.request.urlopen(manifest_url(release), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_model_key(key: str) -> str:
    key = str(key).strip()
    if not MODEL_KEY_RE.fullmatch(key) or ".." in key:
        raise ValueError(f"Invalid DTAG model key: {key!r}")
    return key


def installed(root: Path, key: str) -> bool:
    p = root / key
    return (p / "source_maps").is_dir() and (p / "trees" / "binary").is_dir()


def _check_member(member: tarfile.TarInfo) -> None:
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise RuntimeError(f"Unsafe path in model archive: {member.name!r}")
    if member.issym() or member.islnk() or member.isdev():
        raise RuntimeError(f"Unsupported link/device entry in model archive: {member.name!r}")


def safe_extract_tar_zst(archive: Path, dest: Path) -> None:
    """Extract a .tar.zst without allowing absolute paths, '..' or links."""
    with archive.open("rb") as raw:
        with zstd.ZstdDecompressor().stream_reader(raw) as zr:
            with tarfile.open(fileobj=zr, mode="r|") as tf:
                for member in tf:
                    _check_member(member)
                    try:
                        tf.extract(member, dest, filter="data")
                    except TypeError:
                        tf.extract(member, dest)


def _download(url: str, dest: Path, total: int, progress: Optional[ProgressFn]) -> None:
    done = 0
    with urllib.request.urlopen(url, timeout=120) as r, dest.open("wb") as out:
        length = int(r.headers.get("Content-Length") or total or 0)
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress("downloading", done, length)


def fetch_one(
    root: Path,
    manifest: dict,
    key: str,
    force: bool = False,
    progress: Optional[ProgressFn] = None,
    log: Callable[[str], None] = print,
) -> Path:
    key = validate_model_key(key)
    models = manifest.get("models", {})
    if key not in models:
        raise KeyError(f"Model not found in manifest: {key}")

    dest = root / key
    if installed(root, key) and not force:
        log(f"OK installed: {key} -> {dest}")
        if progress:
            progress("installed", 0, 0)
        return dest

    entry = models[key]
    archive_rel = str(entry["archive"])
    if PurePosixPath(archive_rel).is_absolute() or ".." in PurePosixPath(archive_rel).parts:
        raise RuntimeError(f"Unsafe archive path in manifest for {key}: {archive_rel!r}")
    url = manifest["base_url"].rstrip("/") + "/" + archive_rel
    total = int(entry.get("size_bytes") or 0)

    root.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".dtag-model-", dir=str(dest.parent)) as td:
        tmp = Path(td)
        archive = tmp / Path(archive_rel).name
        log(f"GET {key}")
        log(f"    {url}")
        _download(url, archive, total, progress)

        if progress:
            progress("verifying", 0, total)
        got = sha256_file(archive)
        expected = entry["sha256"]
        if got != expected:
            raise RuntimeError(
                f"SHA256 mismatch for {key}: expected {expected}, got {got}"
            )

        if progress:
            progress("extracting", 0, total)
        extract = tmp / "extract"
        extract.mkdir()
        safe_extract_tar_zst(archive, extract)

        top = extract / Path(key).name
        if not (top / "source_maps").is_dir():
            raise RuntimeError(f"Archive missing source_maps/: {key}")
        if not (top / "trees" / "binary").is_dir():
            raise RuntimeError(f"Archive missing trees/binary/: {key}")

        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(top), str(dest))

    log(f"INSTALLED {key} -> {dest}")
    if progress:
        progress("installed", total, total)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", help="e.g. gss/gss_2024")
    ap.add_argument(
        "--family",
        choices=["gss", "afrobarometer", "wvs", "eurobarometer"],
    )
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--release", default=DEFAULT_RELEASE)
    ap.add_argument("--root", default="")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve() if args.root else default_root()
    manifest = load_manifest(args.release)
    keys = sorted(manifest.get("models", {}))

    if args.list:
        for key in keys:
            flag = "*" if installed(root, key) else " "
            print(f"{flag} {key}")
        return

    if args.all:
        wanted = keys
    elif args.family:
        wanted = [k for k in keys if k.startswith(args.family + "/")]
    elif args.model:
        wanted = [args.model]
    else:
        ap.error("provide MODEL, --family, --all, or --list")

    for key in wanted:
        fetch_one(root, manifest, key, force=args.force)


if __name__ == "__main__":
    main()
