#!/usr/bin/env python3
"""Smoke-test native LSM model directories against the DTAG runtime.

This test intentionally separates model/runtime validation from OpenAI calls.
By default it checks every trained optional native model found in
configs/dtag_config.yaml.  Use --run-openai for an actual one-question DTAG
deployment smoke after the no-LLM checks pass.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import yaml

from model_backend import load_model
import pipeline as core
import pipeline_localized as localized


ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> Dict[str, Any]:
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"Config is not a mapping: {path}")
    return obj


def resolve(root: Path, value: str) -> Path:
    p = Path(str(value)).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def profile_for_model(cfg: Dict[str, Any], key: str) -> List[str]:
    out = []
    for name, spec in (cfg.get("interactive_profiles", {}) or {}).items():
        if isinstance(spec, dict) and str(spec.get("qnet", "")) == key:
            out.append(str(name))
    return out


def map_for_model(cfg: Dict[str, Any], key: str) -> str:
    profiles = cfg.get("interactive_profiles", {}) or {}
    maps = cfg.get("maps", {}) or {}
    for spec in profiles.values():
        if isinstance(spec, dict) and str(spec.get("qnet", "")) == key:
            mk = str(spec.get("map", ""))
            return str(maps.get(mk, mk))
    return ""


def check_model(root: Path, cfg: Dict[str, Any], key: str, path: Path) -> None:
    print(f"\n== {key} ==")
    print(f"path: {path}")

    m = load_model(path, backend="native_lsm")
    nfeat = len(m.feature_names)
    print(f"features: {nfeat}")
    print(f"trees:    {len(m.tree_ids)}")
    if nfeat == 0 or not m.tree_ids:
        raise RuntimeError("No model features/trees")

    possible = m.possible_values()
    nonempty_support = sum(bool(v) for v in possible.values())
    print(f"variables with categorical support: {nonempty_support}/{nfeat}")
    if nonempty_support == 0:
        raise RuntimeError("No categorical source-map support found")

    # One-target prediction from an all-missing state.
    target_id = m.tree_ids[0]
    target_name = m.feature_names[target_id]
    row = np.array([""] * nfeat, dtype=object)
    pred = m.predict_distributions(row, target_names=[target_name])
    dist = pred.get(target_name, {})
    if not dist:
        raise RuntimeError(f"No distribution returned for target {target_name}")
    total = sum(float(x) for x in dist.values())
    print(f"null prediction: {target_name} states={len(dist)} sum={total:.6f}")
    if not (0.999 <= total <= 1.001):
        raise RuntimeError(f"Distribution does not sum to one: {total}")

    # Self-distance is a cheap native qdistance contract check.
    d0 = m.qdistance(row, row)
    print(f"qdistance(NULL,NULL): {d0:.12g}")
    if not np.isfinite(d0) or abs(d0) > 1e-10:
        raise RuntimeError(f"Self qdistance should be zero; got {d0}")

    map_rel = map_for_model(cfg, key)
    if map_rel:
        mp = resolve(root, map_rel)
        if mp.exists():
            df = pd.read_csv(mp, dtype=str).fillna("")
            map_vars = set(df["variable"].astype(str)) if "variable" in df.columns else set()
            qvars = set(m.feature_names)
            inter = qvars & map_vars
            frac = len(inter) / max(1, len(qvars))
            print(f"map overlap: {len(inter)}/{len(qvars)} = {frac:.3f}")
            if frac < 0.50:
                raise RuntimeError(f"Model/map overlap too low: {frac:.3f}")

    # If this model backs an Afrobarometer dev profile, verify hard country
    # conditioning without an LLM.
    if key == "afrobarometer_r5_native":
        feat = set(m.feature_names)
        fa, ma = localized.build_forced_assignments(
            feat, possible, None, "Nigeria", "Africa"
        )
        fb, mb = localized.build_forced_assignments(
            feat, possible, None, "Ghana", "Africa"
        )
        if ma.get("geography_conditioning_mode") != "categorical_country":
            raise RuntimeError(f"Nigeria did not resolve categorically: {ma}")
        if mb.get("geography_conditioning_mode") != "categorical_country":
            raise RuntimeError(f"Ghana did not resolve categorically: {mb}")
        if fa == fb:
            raise RuntimeError("Nigeria/Ghana forced states are identical")
        print(
            "country conditioning: PASS "
            f"feature={ma.get('categorical_country_feature')}"
        )

    print("PASS")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--model", action="append", default=[], help="native config model key")
    ap.add_argument("--run-openai", action="store_true")
    ap.add_argument("--profile", default="", help="profile for --run-openai")
    ap.add_argument(
        "--question",
        default="What do you think about immigration?",
    )
    args = ap.parse_args()

    config_path = resolve(ROOT, args.config)
    cfg = load_config(config_path)
    models = cfg.get("models", {}) or {}
    optional = set(
        map(str, ((cfg.get("development", {}) or {}).get("optional_models", []) or []))
    )

    selected = args.model or sorted(optional)
    checked: List[str] = []
    missing: List[str] = []

    for key in selected:
        if key not in models:
            print(f"UNKNOWN model key: {key}", file=sys.stderr)
            missing.append(key)
            continue
        p = resolve(ROOT, str(models[key]))
        if not p.exists():
            print(f"SKIP not trained: {key} -> {p}")
            missing.append(key)
            continue
        check_model(ROOT, cfg, key, p)
        checked.append(key)

    print("\nSUMMARY")
    print(f"native models checked: {len(checked)}")
    print(f"native models not present: {len(missing)}")
    if checked:
        print("checked:", ", ".join(checked))
    if missing:
        print("missing:", ", ".join(missing))

    if args.run_openai:
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("--run-openai requested but OPENAI_API_KEY is not set")
        profile = args.profile
        if not profile:
            # Prefer GSS 2024 because it tests both normal answer generation and
            # the GSS ideology path once the native model exists.
            profile = "gss2024_native_cm"
        cmd = [
            sys.executable,
            "scripts/interactive.py",
            "--config", str(config_path),
            "--profile", profile,
            "--question", args.question,
        ]
        print("\nOPENAI END-TO-END")
        print(" ".join(cmd))
        raise SystemExit(subprocess.call(cmd, cwd=ROOT))


if __name__ == "__main__":
    main()
