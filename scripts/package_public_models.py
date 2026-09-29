#!/usr/bin/env python3
"""Package the installed DTAG native model corpus for public distribution.

Runtime release archives contain only:
  meta.txt
  source_maps/
  trees/

Training artifact data_set_0 is intentionally excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
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
    ap.add_argument("--model-root", default="models/lsm")
    ap.add_argument("--release", default="v0.2.0")
    ap.add_argument("--bucket", default="git-zeroknowledgediscovery-dtag")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(args.model_root).expanduser().resolve()
    out = (
        Path(args.out).expanduser().resolve()
        if args.out
        else Path("/tmp") / f"dtag-models-{args.release}"
    )
    out.mkdir(parents=True, exist_ok=True)

    base_url = f"https://storage.googleapis.com/{args.bucket}/models/{args.release}"

    manifest = {
        "schema_version": 1,
        "release": args.release,
        "base_url": base_url,
        "models": {},
    }

    total_models = 0
    total_bytes = 0

    for family, expected in EXPECTED.items():
        family_root = root / family
        if not family_root.is_dir():
            raise SystemExit(f"Missing model family directory: {family_root}")

        models = sorted(p for p in family_root.iterdir() if p.is_dir())
        if len(models) != expected:
            raise SystemExit(
                f"{family}: found {len(models)} models; expected {expected}"
            )

        family_out = out / family
        family_out.mkdir(parents=True, exist_ok=True)

        for model in models:
            required = [model / "source_maps", model / "trees" / "binary"]
            missing = [str(p) for p in required if not p.exists()]
            if missing:
                raise SystemExit(
                    f"{family}/{model.name}: missing runtime assets: {missing}"
                )

            archive = family_out / f"{model.name}.tar.gz"
            print(f"PACK {family}/{model.name}")

            with tarfile.open(archive, "w:gz") as tf:
                for name in ("meta.txt", "source_maps", "trees"):
                    src = model / name
                    if src.exists():
                        tf.add(src, arcname=f"{model.name}/{name}")

            digest = sha256_file(archive)
            size = archive.stat().st_size
            total_bytes += size
            total_models += 1

            key = f"{family}/{model.name}"
            manifest["models"][key] = {
                "archive": f"{family}/{archive.name}",
                "sha256": digest,
                "size_bytes": size,
            }

    if total_models != 252:
        raise SystemExit(f"Expected 252 models; packaged {total_models}")

    manifest["model_count"] = total_models
    manifest["total_archive_bytes"] = total_bytes

    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"PASS: packaged {total_models} models")
    print(f"release dir: {out}")
    print(f"manifest:    {manifest_path}")
    print(f"archives:    {total_bytes / 1024**3:.3f} GiB")


if __name__ == "__main__":
    main()
