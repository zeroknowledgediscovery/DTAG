#!/usr/bin/env python3
"""Audit native DTAG model/map completeness across all supported families."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from model_backend import load_model  # noqa: E402


def gss_pairs() -> List[Tuple[str, Path, Path]]:
    out = []
    root = ROOT / "models/lsm/gss"
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            m = re.fullmatch(r"gss_(\d{4})", p.name)
            if not m:
                continue
            year = m.group(1)
            out.append((f"GSS {year}", p, ROOT / f"maps/gss/gss_{year}_map.csv"))
    return out


def afro_pairs() -> List[Tuple[str, Path, Path]]:
    out = []
    root = ROOT / "models/lsm/afrobarometer"
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            m = re.fullmatch(r"r(\d+)", p.name, re.I)
            if not m:
                continue
            r = int(m.group(1))
            out.append((
                f"Afrobarometer R{r}",
                p,
                ROOT / f"maps/afromap/afrobarometer_r{r}_map.csv",
            ))
    return out


def wvs_pairs() -> List[Tuple[str, Path, Path]]:
    p = ROOT / "models/lsm/wvs/wvs7_pooled"
    if not p.is_dir():
        return []
    return [("WVS7 pooled", p, ROOT / "maps/wvs7_variable_question_map.csv")]


def euro_pairs() -> List[Tuple[str, Path, Path]]:
    out = []
    root = ROOT / "models/lsm/eurobarometer"
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            m = re.search(r"(ZA\d+)", p.name, re.I)
            if not m:
                continue
            za = m.group(1).upper()
            out.append((f"Eurobarometer {za}", p, ROOT / f"maps/eurobarometer/{za}_map.csv"))
    return out


def inspect_map(path: Path) -> Tuple[bool, int, set[str], str]:
    if not path.is_file():
        return False, 0, set(), "missing"
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as e:
        return False, 0, set(), f"unreadable: {e}"
    if "variable" not in df.columns:
        return False, len(df), set(), "missing variable column"
    return True, len(df), set(df["variable"].astype(str)), "OK"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true", help="load every model and verify exact feature overlap")
    args = ap.parse_args()

    families: Dict[str, List[Tuple[str, Path, Path]]] = {
        "gss": gss_pairs(),
        "afrobarometer": afro_pairs(),
        "wvs": wvs_pairs(),
        "eurobarometer": euro_pairs(),
    }

    total_models = sum(len(v) for v in families.values())
    total_maps = 0
    missing = []
    bad = []
    overlap_bad = []

    print("FAMILY SUMMARY")
    for family, pairs in families.items():
        nmap = sum(1 for _, _, mp in pairs if mp.is_file())
        total_maps += nmap
        print(f"{family:15s} models={len(pairs):3d} maps={nmap:3d} missing={len(pairs)-nmap:3d}")

    print("\nDETAIL")
    for family, pairs in families.items():
        for name, model_path, map_path in pairs:
            ok, nrows, map_vars, detail = inspect_map(map_path)
            if not ok:
                if detail == "missing":
                    missing.append((name, map_path))
                    print(f"MISS {name}: {map_path.relative_to(ROOT)}")
                else:
                    bad.append((name, detail))
                    print(f"BAD  {name}: {detail}")
                continue

            if args.deep:
                try:
                    model = load_model(model_path, backend="native_lsm")
                    feats = set(map(str, model.feature_names))
                    overlap = len(feats & map_vars)
                    frac = overlap / max(1, len(feats))
                    if overlap != len(feats):
                        overlap_bad.append((name, overlap, len(feats), frac))
                        print(f"WARN {name}: overlap={overlap}/{len(feats)}={frac:.3f}")
                    else:
                        print(f"OK   {name}: overlap=1.000 rows={nrows}")
                except Exception as e:
                    bad.append((name, str(e)))
                    print(f"BAD  {name}: model load failed: {e}")

    print("\nTOTAL")
    print(f"native models: {total_models}")
    print(f"maps present:  {total_maps}")
    print(f"missing maps:  {len(missing)}")
    print(f"bad maps:      {len(bad)}")
    if args.deep:
        print(f"overlap issues:{len(overlap_bad)}")

    expected = {
        "gss": 35,
        "afrobarometer": 9,
        "wvs": 1,
        "eurobarometer": 207,
    }
    count_mismatch = []
    for family, n in expected.items():
        actual = len(families[family])
        if actual != n:
            count_mismatch.append((family, actual, n))

    if count_mismatch:
        print("\nCOUNT MISMATCHES")
        for family, actual, expected_n in count_mismatch:
            print(f"{family}: found {actual}, expected {expected_n}")

    if missing:
        print("\nMISSING MAPS")
        for name, p in missing:
            print(f"{name}: {p.relative_to(ROOT)}")

    if bad:
        print("\nBAD MAPS")
        for name, detail in bad:
            print(f"{name}: {detail}")

    if overlap_bad:
        print("\nMODEL/MAP OVERLAP ISSUES")
        for name, overlap, nfeat, frac in overlap_bad:
            print(f"{name}: {overlap}/{nfeat}={frac:.3f}")

    if count_mismatch or missing or bad or overlap_bad:
        raise SystemExit(1)

    print("\nPASS: native DTAG map surface is complete.")
    print("Expected/verified inventory: 35 GSS + 9 Afrobarometer + 1 WVS + 207 Eurobarometer = 252")


if __name__ == "__main__":
    main()
