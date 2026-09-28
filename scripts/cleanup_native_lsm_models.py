#!/usr/bin/env python3
"""Safely trim native LSM model directories for DTAG runtime use.

Default mode is DRY RUN. Nothing is deleted unless --apply is supplied.

Runtime-required content for the current DTAG native backend:
  KEEP source_maps/              (including source_maps/json_shards/*.json)
  KEEP trees/binary/tree_*.bin
  KEEP meta.txt when present
  KEEP training_manifest.json / manifest.json when present

Redundant runtime content removed by --apply:
  trees/json/
  trees/dot/
  *.json directly under trees/
  *.dot directly under trees/

Optional training-only removal with --drop-training-data:
  data_set_*/
  datasets/
  parsed_data/

The training-data removal is safe for DTAG inference, but should be used only
after the original/prepared CSV and provenance manifest are stored elsewhere.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]


def human(n: int) -> str:
    units = ["B","KiB","MiB","GiB","TiB"]
    x=float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.1f}{u}"
        x/=1024
    return f"{n}B"


def size(path: Path) -> int:
    if path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total=0
    if path.is_dir():
        for p in path.rglob("*"):
            if p.is_file() and not p.is_symlink():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return total


def valid_model(p: Path) -> bool:
    return (p/"source_maps").is_dir() and (p/"trees"/"binary").is_dir()


def discover(root: Path) -> List[Path]:
    out=[]
    if valid_model(root):
        return [root]
    for p in root.rglob("*"):
        if p.is_dir() and valid_model(p):
            out.append(p)
    # avoid nested duplicates
    uniq=[]
    seen=set()
    for p in sorted(out):
        rp=p.resolve()
        if rp not in seen:
            seen.add(rp); uniq.append(rp)
    return uniq


def candidates(model: Path, drop_training: bool) -> List[Tuple[Path,str]]:
    c=[]
    for rel in ["trees/json","trees/dot"]:
        p=model/rel
        if p.exists():
            c.append((p,"redundant tree serialization"))
    trees=model/"trees"
    if trees.is_dir():
        for p in trees.glob("*.json"):
            c.append((p,"redundant tree JSON"))
        for p in trees.glob("*.dot"):
            c.append((p,"redundant tree DOT"))
    if drop_training:
        for p in model.glob("data_set_*"):
            if p.exists():
                c.append((p,"training-only parsed dataset"))
        for rel in ["datasets","parsed_data"]:
            p=model/rel
            if p.exists():
                c.append((p,"training-only parsed dataset"))
    return c


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="models/lsm",
                    help="native model root or one model directory")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; default is dry-run")
    ap.add_argument("--drop-training-data", action="store_true",
                    help="also remove data_set_*/datasets/parsed_data")
    args=ap.parse_args()

    root=Path(args.root).expanduser()
    if not root.is_absolute():
        root=ROOT/root
    root=root.resolve()
    if not root.exists():
        raise SystemExit(f"Missing: {root}")

    models=discover(root)
    if not models:
        raise SystemExit(f"No native LSM model directories found under {root}")

    total=0
    nitems=0
    print("MODE:", "APPLY" if args.apply else "DRY RUN")
    print("IMPORTANT: source_maps/ is never removed.")
    for m in models:
        items=candidates(m,args.drop_training_data)
        if not items:
            continue
        print(f"\n{m}")
        for p,why in items:
            b=size(p); total += b; nitems += 1
            print(f"  {'DELETE' if args.apply else 'would delete'} {p.relative_to(m)}"
                  f"  {human(b):>10}  ({why})")
            if args.apply:
                remove(p)

        # refuse to call a model healthy if required runtime pieces disappeared
        if not valid_model(m):
            raise RuntimeError(f"Required runtime content missing after cleanup: {m}")

    print(f"\nitems: {nitems}")
    print(f"space: {human(total)}")
    if not args.apply:
        print("No files changed. Re-run with --apply after reviewing the list.")


if __name__ == "__main__":
    main()
