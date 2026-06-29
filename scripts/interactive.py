#!/usr/bin/env python3
"""
Run one DTAG interactive/single-question/autoplay session from a YAML/JSON config profile.

This is the config-driven replacement for long handwritten pipeline.py commands.
It reuses the same master config used by scripts/run.py, but reads profiles under:

  interactive_profiles:
    profile_name:
      qnet: model_key_or_path
      map: map_key_or_path
      persona: "..."
      logs_dir: outputs/...
      tag: ...
      year: 2017
      country: India
      continent: Asia
      polar_vectors: ""          # optional; empty disables unless overridden
      run:
        no_ideology: true
        k: 6
        resp_mode: max

Usage:
  python3 scripts/interactive.py --config configs/dtag_config.yaml --profile wvs7_india_2017 --loop
  python3 scripts/interactive.py --config configs/dtag_config.yaml --profile gss2022_wf --question "What do you think about immigration?"
  python3 scripts/interactive.py --config configs/dtag_config.yaml --profile afrobarometer_r5_nigeria --print-command --loop
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


def load_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        obj = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except Exception as e:
            raise SystemExit("YAML config requires PyYAML. Install with: pip install pyyaml") from e
        obj = yaml.safe_load(text)
    if not isinstance(obj, dict):
        raise SystemExit(f"Config must be a mapping/object: {path}")
    return obj


def package_root_for_config(config_path: Path) -> Path:
    if config_path.parent.name == "configs":
        return config_path.parent.parent.resolve()
    return config_path.parent.resolve()


def resolve_path(root: Path, p: Any) -> str:
    text = str(p or "").strip()
    if not text:
        return ""
    pp = Path(text).expanduser()
    if pp.is_absolute():
        return str(pp)
    return str((root / pp).resolve())


def resolve_optional_path(root: Path, value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "false", "off", "disabled"}:
        return ""
    return resolve_path(root, text)


def resolve_named_path(root: Path, cfg: Dict[str, Any], section: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    table = cfg.get(section, {}) or {}
    if isinstance(table, dict) and text in table:
        return resolve_path(root, table[text])
    return resolve_path(root, text)


def add_arg(cmd: List[str], flag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            cmd.append(flag)
    else:
        text = str(value)
        if text != "":
            cmd.extend([flag, text])


def merge_run_cfg(cfg: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    defaults = cfg.get("defaults", {}) or {}
    run_cfg: Dict[str, Any] = dict(defaults.get("run", {}) or {})
    # Interactive sessions should be conservative unless profile overrides.
    interactive_defaults = defaults.get("interactive", {}) or {}
    run_cfg.update(interactive_defaults)
    run_cfg.update(profile.get("run", {}) or {})
    return run_cfg


def get_profile(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    profiles = cfg.get("interactive_profiles", {}) or {}
    if name not in profiles:
        raise SystemExit(f"Unknown interactive profile {name!r}. Use --list to see names.")
    profile = profiles[name]
    if not isinstance(profile, dict):
        raise SystemExit(f"interactive_profiles.{name} must be a mapping/object")
    return profile


def build_command(
    root: Path,
    cfg: Dict[str, Any],
    profile_name: str,
    profile: Dict[str, Any],
    question: str,
    loop: bool,
    autoplay_csv: str,
    extra_args: str,
) -> List[str]:
    defaults = cfg.get("defaults", {}) or {}
    run_cfg = merge_run_cfg(cfg, profile)

    py = str(run_cfg.get("python", sys.executable or "python3"))
    pipeline = resolve_path(root, profile.get("pipeline", defaults.get("pipeline", "scripts/pipeline.py")))
    qnet = resolve_named_path(root, cfg, "models", profile.get("qnet", ""))
    map_path = resolve_named_path(root, cfg, "maps", profile.get("map", ""))
    persona = str(profile.get("persona", "")).strip()
    if not qnet:
        raise SystemExit(f"Profile {profile_name!r} missing qnet")
    if not map_path:
        raise SystemExit(f"Profile {profile_name!r} missing map")
    if not persona:
        raise SystemExit(f"Profile {profile_name!r} missing persona")

    assets_dir = resolve_path(root, profile.get("assets_dir", defaults.get("assets_dir", "assets")))
    logs_dir = resolve_path(root, profile.get("logs_dir", f"outputs/{profile_name}"))
    tag = str(profile.get("tag", profile_name)).strip() or profile_name
    polar = resolve_optional_path(root, profile.get("polar_vectors", defaults.get("polar_vectors", "")))

    cmd = [py, pipeline, "--qnet", qnet, "--map", map_path, "--persona", persona]
    cmd.extend(["--assets_dir", assets_dir, "--logs_dir", logs_dir, "--tag", tag])
    if polar:
        cmd.extend(["--polar_vectors", polar])

    for key, flag in [
        ("year", "--year"),
        ("country", "--country"),
        ("continent", "--continent"),
    ]:
        value = profile.get(key, None)
        if value is not None and str(value).strip():
            add_arg(cmd, flag, value)

    for key, flag in [
        ("state_keep", "--state_keep"),
        ("k", "--k"),
        ("prefilter", "--prefilter"),
        ("min_map_score", "--min_map_score"),
        ("semantic_fallback", "--semantic_fallback"),
        ("semantic_k", "--semantic_k"),
        ("semantic_prefilter", "--semantic_prefilter"),
        ("semantic_min_confidence", "--semantic_min_confidence"),
        ("semantic_embedding_model", "--semantic_embedding_model"),
        ("semantic_resp_mode", "--semantic_resp_mode"),
        ("max_assign", "--max_assign"),
        ("assign_prefilter", "--assign_prefilter"),
        ("resp_mode", "--resp_mode"),
        ("openai_model", "--openai_model"),
        ("seed", "--seed"),
    ]:
        if key in run_cfg:
            add_arg(cmd, flag, run_cfg[key])

    if run_cfg.get("timing", False):
        cmd.append("--timing")
    if run_cfg.get("no_ideology", False):
        cmd.append("--no_ideology")
    if run_cfg.get("require_polar_vectors", False):
        cmd.append("--require_polar_vectors")

    mode_count = sum(bool(x) for x in [question.strip(), loop, autoplay_csv.strip()])
    if mode_count != 1:
        raise SystemExit("Choose exactly one mode: --question TEXT, --loop, or --autoplay_csv PATH")
    if question.strip():
        cmd.extend(["--question", question.strip()])
    elif loop:
        cmd.append("--loop")
    else:
        cmd.extend(["--autoplay_csv", resolve_path(root, autoplay_csv)])

    if extra_args.strip():
        cmd.extend(shlex.split(extra_args))
    if str(profile.get("extra_pipeline_args", "")).strip():
        cmd.extend(shlex.split(str(profile["extra_pipeline_args"])))
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser(description="Run DTAG pipeline.py from a named interactive config profile.")
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--profile", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--question", default="")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--autoplay_csv", default="")
    ap.add_argument("--print-command", action="store_true")
    ap.add_argument("--extra", default="", help="Extra raw pipeline args appended after profile args")
    args = ap.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    cfg = load_config(config_path)
    root = package_root_for_config(config_path)

    profiles = cfg.get("interactive_profiles", {}) or {}
    if args.list:
        print("Available interactive profiles:")
        for name in sorted(profiles.keys()):
            desc = ""
            p = profiles.get(name, {})
            if isinstance(p, dict):
                desc = str(p.get("description", "")).strip()
            print(f"  {name}" + (f"  - {desc}" if desc else ""))
        return

    if not args.profile:
        raise SystemExit("Provide --profile, or use --list")

    profile = get_profile(cfg, args.profile)
    cmd = build_command(root, cfg, args.profile, profile, args.question, args.loop, args.autoplay_csv, args.extra)

    print("COMMAND")
    print(" ".join(shlex.quote(x) for x in cmd))
    print()

    if args.print_command:
        return
    raise SystemExit(subprocess.call(cmd, cwd=str(root)))


if __name__ == "__main__":
    main()
