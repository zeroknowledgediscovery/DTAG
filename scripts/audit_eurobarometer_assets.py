#!/usr/bin/env python3
"""Audit Eurobarometer native models, codebooks, maps, and fallback provenance.

Development policy:
- model + map => runnable
- codebook-backed map => exact semantic map
- no-codebook union map => runnable fallback, reported as WARN/technical debt
- missing map => not runnable for semantic DTAG use
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models/lsm/eurobarometer"
CODEBOOKS = ROOT / "data/eurobarometer/codebooks"
MAPS = ROOT / "maps/eurobarometer"


def za_from_name(name: str):
    m = re.search(r"(ZA\d+)", str(name), re.I)
    return m.group(1).upper() if m else None


def fallback_stats(path: Path):
    counts = Counter()
    n = 0
    if not path.is_file():
        return n, counts
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                n += 1
                p = str(row.get("map_provenance", "")).strip()
                if not p:
                    src = str(row.get("source", "")).lower()
                    if "gesis" in src:
                        p = "GESIS_EXACT"
                    elif "union" in src:
                        p = "UNION_FALLBACK"
                    else:
                        p = "UNKNOWN"
                counts[p] += 1
    except Exception:
        counts["READ_ERROR"] += 1
    return n, counts


models = {}
if MODELS.is_dir():
    for p in MODELS.iterdir():
        if p.is_dir():
            za = za_from_name(p.name)
            if za:
                models.setdefault(za, []).append(p)

codebooks = {}
if CODEBOOKS.is_dir():
    for p in CODEBOOKS.glob("ZA*_cdb.pdf"):
        za = za_from_name(p.name)
        if za:
            codebooks[za] = p

maps = {}
if MAPS.is_dir():
    for p in MAPS.glob("ZA*_map.csv"):
        za = za_from_name(p.name)
        if za:
            maps[za] = p

allza = sorted(set(models) | set(codebooks) | set(maps), key=lambda z: int(z[2:]))

print("ZA,MODEL,CODEBOOK,MAP,MAP_KIND,RESOLVED_FRACTION")
fallback_details = {}
for za in allza:
    has_model = za in models
    has_cb = za in codebooks
    has_map = za in maps

    kind = "MISSING"
    resolved_fraction = ""
    if has_map and has_cb:
        kind = "EXACT_GESIS"
        resolved_fraction = "1.000"
    elif has_map:
        kind = "UNION_FALLBACK"
        n, counts = fallback_stats(maps[za])
        unresolved = counts.get("UNRESOLVED_NATIVE", 0)
        resolved = max(0, n - unresolved)
        resolved_fraction = f"{resolved / max(1, n):.3f}"
        fallback_details[za] = (n, counts, resolved / max(1, n))

    print(
        f"{za},{'YES' if has_model else 'NO'},"
        f"{'YES' if has_cb else 'NO'},"
        f"{'YES' if has_map else 'NO'},"
        f"{kind},{resolved_fraction}"
    )

installed = sorted(models, key=lambda z: int(z[2:]))
missing_cb = [z for z in installed if z not in codebooks]
missing_map = [z for z in installed if z not in maps]
runnable = [z for z in installed if z in maps]
exact = [z for z in installed if z in maps and z in codebooks]
fallback = [z for z in installed if z in maps and z not in codebooks]

print("\nSUMMARY")
print("installed native models:", len(installed))
print("downloaded codebooks:   ", len(codebooks))
print("generated maps:         ", len(maps))
print("runnable model+map:     ", len(runnable))
print("exact GESIS maps:       ", len(exact))
print("union fallback maps:    ", len(fallback))
print("models missing codebook:", len(missing_cb))
print("models missing map:     ", len(missing_map))

if fallback:
    total_vars = sum(x[0] for x in fallback_details.values())
    unresolved = sum(x[1].get("UNRESOLVED_NATIVE", 0) for x in fallback_details.values())
    resolved = total_vars - unresolved
    print("fallback variables:     ", total_vars)
    print("fallback resolved:      ", resolved)
    print("fallback unresolved:    ", unresolved)
    print("fallback resolved frac: ", f"{resolved / max(1, total_vars):.3f}")

    print("\nFALLBACK MAPS (RUNNABLE, IMPROVABLE)")
    for za in fallback:
        n, counts, frac = fallback_details.get(za, (0, Counter(), 0.0))
        print(
            f"{za}: resolved={frac:.3f}; "
            f"consensus={counts.get('UNION_CONSENSUS', 0)}; "
            f"support={counts.get('UNION_SUPPORT_MATCH', 0)}; "
            f"context={counts.get('UNION_CONTEXT_MATCH', 0)}; "
            f"unresolved={counts.get('UNRESOLVED_NATIVE', 0)}"
        )

if missing_cb:
    print("\nMISSING CODEBOOKS (NONBLOCKING IF FALLBACK MAP EXISTS)")
    print(" ".join(missing_cb))

if missing_map:
    print("\nMISSING MAPS (BLOCKING FOR THOSE WAVES)")
    print(" ".join(missing_map))
