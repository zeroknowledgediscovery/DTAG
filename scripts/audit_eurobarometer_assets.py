#!/usr/bin/env python3
"""Audit Eurobarometer native models, downloaded codebooks, and generated maps."""
from __future__ import annotations
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODELS=ROOT/"models/lsm/eurobarometer"
CODEBOOKS=ROOT/"data/eurobarometer/codebooks"
MAPS=ROOT/"maps/eurobarometer"

def za_from_name(name: str):
    m=re.search(r"(ZA\d+)", name, re.I)
    return m.group(1).upper() if m else None

models={}
if MODELS.is_dir():
    for p in MODELS.iterdir():
        if p.is_dir():
            za=za_from_name(p.name)
            if za: models.setdefault(za,[]).append(p)

codebooks={}
if CODEBOOKS.is_dir():
    for p in CODEBOOKS.glob("ZA*_cdb.pdf"):
        za=za_from_name(p.name)
        if za: codebooks[za]=p

maps={}
if MAPS.is_dir():
    for p in MAPS.glob("ZA*_map.csv"):
        za=za_from_name(p.name)
        if za: maps[za]=p

allza=sorted(set(models)|set(codebooks)|set(maps), key=lambda z:int(z[2:]))
print("ZA,MODEL,CODEBOOK,MAP")
for za in allza:
    print(f"{za},{'YES' if za in models else 'NO'},"
          f"{'YES' if za in codebooks else 'NO'},"
          f"{'YES' if za in maps else 'NO'}")

installed=sorted(models, key=lambda z:int(z[2:]))
missing_cb=[z for z in installed if z not in codebooks]
missing_map=[z for z in installed if z not in maps]
ready=[z for z in installed if z in codebooks and z in maps]

print("\nSUMMARY")
print("installed native models:", len(installed))
print("downloaded codebooks:   ", len(codebooks))
print("generated maps:         ", len(maps))
print("fully ready:            ", len(ready))
print("models missing codebook:", len(missing_cb))
print("models missing map:     ", len(missing_map))
if missing_cb:
    print("\nMISSING CODEBOOKS")
    print(" ".join(missing_cb))
if missing_map:
    print("\nMISSING MAPS")
    print(" ".join(missing_map))
