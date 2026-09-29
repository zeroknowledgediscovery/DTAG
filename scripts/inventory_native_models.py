#!/usr/bin/env python3
"""Inventory all native LSM models installed for DTAG."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm"
sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402


def inspect_model(path: Path) -> dict:
    out = {
        "path": str(path.relative_to(ROOT)),
        "family": path.parent.name,
        "name": path.name,
        "valid_layout": False,
        "features": None,
        "trees": None,
        "usable_trees": None,
        "error": None,
    }
    out["valid_layout"] = (
        (path / "source_maps").is_dir()
        and (path / "trees" / "binary").is_dir()
    )
    if not out["valid_layout"]:
        return out
    try:
        m = load_model(path, backend="native_lsm")
        out["features"] = len(m.feature_names)
        out["trees"] = len(m.tree_ids)
        out["usable_trees"] = len(getattr(m, "usable_tree_ids", m.tree_ids))
    except Exception as e:
        out["error"] = str(e)
    return out


def discover_models() -> list[Path]:
    if not MODEL_ROOT.is_dir():
        return []
    out = []
    for family in sorted(p for p in MODEL_ROOT.iterdir() if p.is_dir()):
        for model in sorted(p for p in family.iterdir() if p.is_dir()):
            if (
                (model / "source_maps").is_dir()
                or (model / "trees" / "binary").is_dir()
            ):
                out.append(model)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--family", default="", help="optional family filter")
    args = ap.parse_args()

    paths = discover_models()
    if args.family:
        paths = [p for p in paths if p.parent.name == args.family]

    rows = [inspect_model(p) for p in paths]

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    counts = {}
    failures = 0
    for r in rows:
        ok = r["valid_layout"] and not r["error"]
        status = "OK" if ok else "FAIL"
        counts[r["family"]] = counts.get(r["family"], 0) + 1
        failures += 0 if ok else 1
        print(
            f'{status:4} {r["path"]} '
            f'features={r["features"]} trees={r["trees"]} '
            f'usable={r["usable_trees"]}'
        )
        if r["error"]:
            print("     error:", r["error"])

    print("\nSUMMARY")
    print("models:", len(rows))
    print("failures:", failures)
    for family in sorted(counts):
        print(f"{family}: {counts[family]}")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
