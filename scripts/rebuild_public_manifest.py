#!/usr/bin/env python3
"""Rebuild manifest.json from an existing DTAG .tar.zst release tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED = {
    "gss": 35,
    "afrobarometer": 9,
    "wvs": 1,
    "eurobarometer": 207,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("release_dir")
    ap.add_argument("--release", default="v0.2.0")
    ap.add_argument("--bucket", default="git-zeroknowledgediscovery-dtag")
    args = ap.parse_args()

    root = Path(args.release_dir).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Release directory not found: {root}")

    manifest = {
        "schema_version": 1,
        "release": args.release,
        "base_url": (
            f"https://storage.googleapis.com/{args.bucket}/"
            f"models/{args.release}"
        ),
        "models": {},
    }

    total = 0
    total_bytes = 0

    for family, expected in EXPECTED.items():
        family_dir = root / family
        archives = sorted(family_dir.glob("*.tar.zst"))
        if len(archives) != expected:
            raise SystemExit(
                f"{family}: found {len(archives)} .tar.zst archives; "
                f"expected {expected}"
            )

        for archive in archives:
            model_name = archive.name.removesuffix(".tar.zst")
            key = f"{family}/{model_name}"
            size = archive.stat().st_size
            print(f"HASH {key}")
            manifest["models"][key] = {
                "archive": f"{family}/{archive.name}",
                "sha256": sha256_file(archive),
                "size_bytes": size,
            }
            total += 1
            total_bytes += size

    if total != 252:
        raise SystemExit(f"Expected 252 archives; found {total}")

    manifest["model_count"] = total
    manifest["total_archive_bytes"] = total_bytes

    out = root / "manifest.json"
    out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"PASS: manifest rebuilt for {total} models")
    print(f"manifest: {out}")
    print(f"compressed total: {total_bytes / 1024**3:.3f} GiB")


if __name__ == "__main__":
    main()
