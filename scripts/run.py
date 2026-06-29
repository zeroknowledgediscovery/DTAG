#!/usr/bin/env python3
"""
Run a DTAG experiment from a master YAML/JSON config file.

Typical use:
  python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_divergence
  python3 scripts/run.py --config configs/dtag_config.yaml --list
  python3 scripts/run.py --config configs/dtag_config.yaml --experiment gss2022_divergence --dry-run
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
    if path.suffix.lower() in {".json"}:
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise SystemExit("YAML config requires PyYAML. Install with: pip install pyyaml") from e
    obj = yaml.safe_load(text)
    if not isinstance(obj, dict):
        raise SystemExit(f"Config must be a mapping/object: {path}")
    return obj


def package_root_for_config(config_path: Path) -> Path:
    # Default package layout: DTAG_clean_setup/configs/dtag_config.yaml
    if config_path.parent.name == "configs":
        return config_path.parent.parent.resolve()
    return config_path.parent.resolve()


def resolve_path(root: Path, p: str) -> str:
    pp = Path(str(p)).expanduser()
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


def resolve_named_path(root: Path, cfg: Dict[str, Any], section: str, value: str) -> str:
    table = cfg.get(section, {}) or {}
    if isinstance(table, dict) and value in table:
        return resolve_path(root, str(table[value]))
    return resolve_path(root, value)


def get_experiment(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    exps = cfg.get("experiments", {}) or {}
    if name not in exps:
        raise SystemExit(f"Unknown experiment {name!r}. Use --list to see names.")
    exp = exps[name]
    if not isinstance(exp, dict):
        raise SystemExit(f"Experiment {name!r} must be a mapping/object.")
    return exp


def materialize_personas(root: Path, cfg: Dict[str, Any], exp: Dict[str, Any], exp_name: str) -> str:
    personas = exp.get("personas", [])
    if not isinstance(personas, list) or not personas:
        raise SystemExit(f"Experiment {exp_name!r} has no personas list")
    out = []
    for p in personas:
        if not isinstance(p, dict):
            raise SystemExit("Each persona must be an object")
        item = dict(p)
        if "qnet" not in item:
            raise SystemExit(f"Persona {p.get('id','?')} missing qnet")
        item["qnet"] = resolve_named_path(root, cfg, "models", str(item["qnet"]))
        out.append(item)
    gen_dir = root / "outputs" / "_generated_configs"
    gen_dir.mkdir(parents=True, exist_ok=True)
    out_path = gen_dir / f"{exp_name}.personas.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return str(out_path)


def question_set_spec(cfg: Dict[str, Any], exp: Dict[str, Any]) -> Dict[str, Any]:
    qsets = cfg.get("question_sets", {}) or {}
    key = exp.get("question_set")
    if key is None:
        qlist = exp.get("question_sets")
        if isinstance(qlist, list) and len(qlist) == 1:
            key = qlist[0]
        elif isinstance(qlist, list) and len(qlist) > 1:
            raise SystemExit(
                "This runner expects one question_set per experiment. "
                "Define separate experiments for multiple question-set groups."
            )
        else:
            raise SystemExit("Experiment must specify question_set")
    key = str(key)
    if key in qsets:
        spec = qsets[key]
        if not isinstance(spec, dict):
            raise SystemExit(f"question_sets.{key} must be an object")
        return spec
    # Allow direct path shorthand.
    return {"dir": key, "glob": "*.csv"}


def add_arg(cmd: List[str], name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            cmd.append(name)
    else:
        cmd.extend([name, str(value)])


def build_command(root: Path, cfg: Dict[str, Any], exp_name: str, exp: Dict[str, Any], cli_dry_run: bool) -> List[str]:
    defaults = cfg.get("defaults", {}) or {}
    run_cfg = dict(defaults.get("run", {}) or {})
    run_cfg.update(exp.get("run", {}) or {})

    qspec = question_set_spec(cfg, exp)
    qdir = resolve_path(root, str(qspec.get("dir", "")))
    qglob = str(qspec.get("glob", "*.csv"))

    pipeline = resolve_path(root, str(exp.get("pipeline", defaults.get("pipeline", "scripts/pipeline.py"))))
    run_grid = resolve_path(root, str(defaults.get("run_grid", "scripts/run_grid.py")))
    map_path = resolve_named_path(root, cfg, "maps", str(exp.get("map", defaults.get("map", ""))))
    polar = resolve_optional_path(root, exp.get("polar_vectors", defaults.get("polar_vectors", "")))
    outdir = resolve_path(root, str(exp.get("outdir", f"outputs/{exp_name}")))
    personas_json = materialize_personas(root, cfg, exp, exp_name)

    py = str(run_cfg.get("python", sys.executable or "python3"))
    cmd = [py, run_grid]
    cmd.extend(["--pipeline", pipeline])
    cmd.extend(["--question_dir", qdir])
    cmd.extend(["--question_glob", qglob])
    cmd.extend(["--outdir", outdir])
    cmd.extend(["--map", map_path])
    if polar:
        cmd.extend(["--polar_vectors", polar])
    cmd.extend(["--personas_json", personas_json])

    for key, flag in [
        ("runs_per_condition", "--runs_per_condition"),
        ("parallel", "--parallel"),
        ("variants", "--variants"),
        ("shuffle_orders", "--shuffle_orders"),
        ("seed_base", "--seed_base"),
        ("openai_model", "--openai_model"),
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
    ]:
        if key in run_cfg:
            add_arg(cmd, flag, run_cfg[key])

    if run_cfg.get("timing", False):
        cmd.append("--timing")
    if run_cfg.get("no_ideology", False):
        cmd.append("--no_ideology")
    if run_cfg.get("require_polar_vectors", False):
        cmd.append("--require_polar_vectors")
    if run_cfg.get("overwrite", False):
        cmd.append("--overwrite")
    if cli_dry_run or run_cfg.get("dry_run", False):
        cmd.append("--dry_run")

    extra = str(run_cfg.get("extra_pipeline_args", "")).strip()
    if extra:
        cmd.extend(["--extra_pipeline_args", extra])

    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--experiment", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print-command", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    cfg = load_config(config_path)
    root = package_root_for_config(config_path)

    if args.list:
        print("Available experiments:")
        for name in sorted((cfg.get("experiments", {}) or {}).keys()):
            print(f"  {name}")
        return

    if not args.experiment:
        raise SystemExit("Provide --experiment, or use --list")

    exp = get_experiment(cfg, args.experiment)
    cmd = build_command(root, cfg, args.experiment, exp, cli_dry_run=args.dry_run)

    print("COMMAND")
    print(" ".join(shlex.quote(x) for x in cmd))
    print()

    if args.print_command:
        return
    raise SystemExit(subprocess.call(cmd, cwd=str(root)))


if __name__ == "__main__":
    main()
