#!/usr/bin/env python3
"""Resolve DTAG ideology poles against a specific native model's labels.

The canonical poles (``assets/polar_vectors/polar_vectors.csv``) are written
once, in one wording. GSS waves differ in which items exist and in how answer
labels are spelled ("legal" vs "should be legal"). A pole answer the model
does not recognise must never be written into a pole state, because it then
silently stops constraining the model.

``resolve_poles`` maps the canonical poles onto one model's variables/labels:

1. item present in the model -> use it;
   item absent but the GSS 2021 split-ballot pair ``<item>v`` / ``<item>nv``
   (same question, with/without a volunteered web response) exists -> use both;
   otherwise the item is dropped for this wave ("item not in wave");
2. each answer: exact label -> kept; otherwise a documented correction from
   ``assets/polar_vectors/gss_pole_corrections.csv`` whose corrected label is
   in the model -> corrected; otherwise unresolved;
3. an item is kept only if **both** its L and R answers resolve (the pair stays
   symmetric); otherwise it is dropped and reported.

Every decision is returned as a report row.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL = REPO_ROOT / "assets" / "polar_vectors" / "polar_vectors.csv"
CORRECTIONS = REPO_ROOT / "assets" / "polar_vectors" / "gss_pole_corrections.csv"
WAVE_DIR = REPO_ROOT / "assets" / "polar_vectors" / "gss"

Report = List[Dict[str, str]]


def load_corrections(path: Path = CORRECTIONS) -> Dict[Tuple[str, str, str], List[str]]:
    out: Dict[Tuple[str, str, str], List[str]] = {}
    if not Path(path).is_file():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            key = (row["variable"].strip(), row["pole"].strip().upper(), row["original"].strip())
            out[key] = [c.strip() for c in row["corrected"].split("|") if c.strip()]
    return out


def _targets(item: str, support: Dict[str, List[str]]) -> Tuple[List[str], str]:
    if support.get(item):
        return [item], "exact_item"
    split = [f"{item}v", f"{item}nv"]
    if all(support.get(s) for s in split):
        return split, "split_ballot_2021"
    return [], "item_not_in_wave"


def _resolve_value(item: str, side: str, value: str, labels: List[str],
                   corrections: Dict[Tuple[str, str, str], List[str]]) -> Tuple[Optional[str], str]:
    if value in labels:
        return value, "exact"
    for cand in corrections.get((item, side, value), []):
        if cand in labels:
            return cand, "corrected"
    return None, "unresolved"


def resolve_poles(
    left: Dict[str, str],
    right: Dict[str, str],
    support: Dict[str, List[str]],
    corrections: Optional[Dict[Tuple[str, str, str], List[str]]] = None,
) -> Tuple[Dict[str, str], Dict[str, str], Report]:
    """Map canonical poles onto a model's variables/labels (see module doc)."""
    corrections = load_corrections() if corrections is None else corrections
    L: Dict[str, str] = {}
    R: Dict[str, str] = {}
    report: Report = []
    for item in sorted(set(left) | set(right)):
        lv, rv = left.get(item), right.get(item)
        if lv is None or rv is None:
            report.append({"item": item, "variable": "", "status": "dropped",
                           "reason": "canonical pole defines only one side",
                           "L_original": lv or "", "L_used": "", "R_original": rv or "", "R_used": ""})
            continue
        targets, how = _targets(item, support)
        if not targets:
            report.append({"item": item, "variable": "", "status": "dropped", "reason": "item not in wave",
                           "L_original": lv, "L_used": "", "R_original": rv, "R_used": ""})
            continue
        for var in targets:
            labels = support.get(var, [])
            l_used, l_how = _resolve_value(item, "L", lv, labels, corrections)
            r_used, r_how = _resolve_value(item, "R", rv, labels, corrections)
            if l_used is None or r_used is None or l_used == r_used:
                bad = []
                if l_used is None:
                    bad.append(f"L answer {lv!r} not in labels")
                if r_used is None:
                    bad.append(f"R answer {rv!r} not in labels")
                if l_used is not None and l_used == r_used:
                    bad.append("L and R resolve to the same label")
                report.append({"item": item, "variable": var, "status": "dropped",
                               "reason": "; ".join(bad) + f" {sorted(labels)}",
                               "L_original": lv, "L_used": l_used or "", "R_original": rv, "R_used": r_used or ""})
                continue
            L[var], R[var] = l_used, r_used
            notes = []
            if how == "split_ballot_2021":
                notes.append(f"item {item!r} is split into {var!r} in this wave")
            for side, h, orig, used in (("L", l_how, lv, l_used), ("R", r_how, rv, r_used)):
                if h == "corrected":
                    notes.append(f"{side}: {orig!r} -> {used!r}")
            status = "kept" if not notes else ("renamed" if how != "exact_item" and len(notes) == 1 else "corrected")
            report.append({"item": item, "variable": var, "status": status, "reason": "; ".join(notes),
                           "L_original": lv, "L_used": l_used, "R_original": rv, "R_used": r_used})
    return L, R, report


def wave_file(model_path: str) -> Optional[Path]:
    """The corrected pole file for a GSS wave model directory, if present."""
    m = re.search(r"gss_(\d{4})$", str(model_path).rstrip("/"))
    if not m:
        return None
    p = WAVE_DIR / f"gss_{m.group(1)}_polar_vectors.csv"
    return p if p.is_file() else None


def is_canonical(path: str) -> bool:
    try:
        return Path(path).resolve() == CANONICAL.resolve()
    except Exception:
        return False


def write_pole_csv(path: Path, L: Dict[str, str], R: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["variable", "R", "L"])
        for v in sorted(L):
            w.writerow([v, R[v], L[v]])
