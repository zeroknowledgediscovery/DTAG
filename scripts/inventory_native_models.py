#!/usr/bin/env python3
"""Inventory native LSM GSS and Eurobarometer models currently installed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402


def inspect_model(path: Path) -> dict:
    out = {
        "path": str(path.relative_to(ROOT)),
        "exists": path.exists(),
        "valid_layout": False,
        "features": None,
        "trees": None,
        "error": None,
    }
    if not path.is_dir():
        return out
    out["valid_layout"] = (path / "source_maps").is_dir() and (path / "trees" / "binary").is_dir()
    if not out["valid_layout"]:
        return out
    try:
        m = load_model(path, backend="native_lsm")
        out["features"] = len(m.feature_names)
        out["trees"] = len(m.tree_ids)
    except Exception as e:
        out["error"] = str(e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    paths = [
        ROOT / "models/lsm/gss/gss_2018",
        ROOT / "models/lsm/gss/gss_2022",
        ROOT / "models/lsm/gss/gss_2024",
    ]
    euro = ROOT / "models/lsm/eurobarometer"
    if euro.is_dir():
        paths.extend(sorted(p for p in euro.iterdir() if p.is_dir()))

    rows = [inspect_model(p) for p in paths]
    if args.json:
        print(json.dumps(rows, indent=2))
        return

    for r in rows:
        status = "OK" if r["valid_layout"] and not r["error"] else "FAIL"
        print(
            f'{status:4} {r["path"]} '
            f'features={r["features"]} trees={r["trees"]}'
        )
        if r["error"]:
            print("     error:", r["error"])


if __name__ == "__main__":
    main()
