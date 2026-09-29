#!/usr/bin/env python3
"""Fetch public DTAG native models into the local model cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
import zstandard as zstd
from pathlib import Path

DEFAULT_RELEASE = os.environ.get("DTAG_MODEL_RELEASE", "v0.2.0")
DEFAULT_BUCKET = os.environ.get(
    "DTAG_PUBLIC_BUCKET", "git-zeroknowledgediscovery-dtag"
)


def default_root() -> Path:
    env = os.environ.get("DTAG_MODEL_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".cache" / "dtag" / "models").resolve()


def manifest_url(release: str) -> str:
    override = os.environ.get("DTAG_MODEL_MANIFEST_URL", "").strip()
    if override:
        return override
    return (
        f"https://storage.googleapis.com/{DEFAULT_BUCKET}/"
        f"models/{release}/manifest.json"
    )


def load_manifest(release: str) -> dict:
    with urllib.request.urlopen(manifest_url(release), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def installed(root: Path, key: str) -> bool:
    p = root / key
    return (p / "source_maps").is_dir() and (p / "trees" / "binary").is_dir()


def fetch_one(root: Path, manifest: dict, key: str, force: bool = False) -> Path:
    models = manifest.get("models", {})
    if key not in models:
        raise KeyError(f"Model not found in manifest: {key}")

    dest = root / key
    if installed(root, key) and not force:
        print(f"OK installed: {key} -> {dest}")
        return dest

    entry = models[key]
    url = manifest["base_url"].rstrip("/") + "/" + entry["archive"]

    root.mkdir(parents=True, exist_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dtag-model-") as td:
        tmp = Path(td)
        archive = tmp / Path(entry["archive"]).name
        print(f"GET {key}")
        print(f"    {url}")
        urllib.request.urlretrieve(url, archive)

        got = sha256_file(archive)
        expected = entry["sha256"]
        if got != expected:
            raise RuntimeError(
                f"SHA256 mismatch for {key}: expected {expected}, got {got}"
            )

        extract = tmp / "extract"
        extract.mkdir()
        with archive.open("rb") as raw:
            with zstd.ZstdDecompressor().stream_reader(raw) as zr:
                with tarfile.open(fileobj=zr, mode="r|") as tf:
                    try:
                        tf.extractall(extract, filter="data")
                    except TypeError:
                        tf.extractall(extract)

        top = extract / Path(key).name
        if not (top / "source_maps").is_dir():
            raise RuntimeError(f"Archive missing source_maps/: {key}")
        if not (top / "trees" / "binary").is_dir():
            raise RuntimeError(f"Archive missing trees/binary/: {key}")

        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(top), str(dest))

    print(f"INSTALLED {key} -> {dest}")
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
