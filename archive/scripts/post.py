#!/usr/bin/env python3
"""
Postprocess a DTAG experiment from the same master YAML/JSON config file used by scripts/run.py.

Typical use:
  python3 scripts/post.py --config configs/dtag_config.yaml --experiment gss2022_divergence
  python3 scripts/post.py --config configs/dtag_config.yaml --experiment gss2022_divergence --dark --transparent
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
    if config_path.parent.name == "configs":
        return config_path.parent.parent.resolve()
    return config_path.parent.resolve()


def resolve_path(root: Path, p: str) -> str:
    pp = Path(str(p)).expanduser()
    if pp.is_absolute():
        return str(pp)
    return str((root / pp).resolve())


def get_experiment(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    exps = cfg.get("experiments", {}) or {}
    if name not in exps:
        raise SystemExit(f"Unknown experiment {name!r}. Use scripts/run.py --list.")
    exp = exps[name]
    if not isinstance(exp, dict):
        raise SystemExit(f"Experiment {name!r} must be an object")
    return exp


def add_arg(cmd: List[str], name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        if value:
            cmd.append(name)
    else:
        cmd.extend([name, str(value)])


def build_command(root: Path, cfg: Dict[str, Any], exp_name: str, exp: Dict[str, Any], args) -> List[str]:
    defaults = cfg.get("defaults", {}) or {}
    post_cfg = dict(defaults.get("postprocess", {}) or {})
    post_cfg.update(exp.get("postprocess", {}) or {})

    postprocess = resolve_path(root, str(defaults.get("postprocess_script", "scripts/postprocess.py")))
    outdir = resolve_path(root, str(exp.get("outdir", f"outputs/{exp_name}")))
    py = str(post_cfg.get("python", sys.executable or "python3"))

    cmd = [py, postprocess, "--batch_out", outdir]

    for key, flag in [
        ("center_mode", "--center_mode"),
        ("center", "--center"),
        ("effect_threshold", "--effect_threshold"),
        ("epsilon", "--epsilon"),
        ("min_reps", "--min_reps"),
        ("bootstrap", "--bootstrap"),
        ("seed", "--seed"),
        ("plot_variant", "--plot_variant"),
        ("quadrant_variant", "--quadrant_variant"),
        ("plot_ci", "--plot_ci"),
        ("plot_dpi", "--plot_dpi"),
        ("band_alpha", "--band_alpha"),
        ("grid_alpha", "--grid_alpha"),
        ("traj_width", "--traj_width"),
        ("traj_height", "--traj_height"),
        ("summary_width", "--summary_width"),
        ("summary_height", "--summary_height"),
    ]:
        if key in post_cfg:
            add_arg(cmd, flag, post_cfg[key])

    label = str(post_cfg.get("label_map_csv", "")).strip()
    if label:
        add_arg(cmd, "--label_map_csv", resolve_path(root, label))

    # Plot flags default to true for the clean workflow, unless explicitly disabled.
    if post_cfg.get("make_plots", True):
        cmd.append("--make_plots")
    if post_cfg.get("quadrant_plot", True):
        cmd.append("--quadrant_plot")
    if post_cfg.get("quadrant_full_labels", False):
        cmd.append("--quadrant_full_labels")
    if post_cfg.get("pdf", True):
        cmd.append("--pdf")
    if post_cfg.get("zip_plots", True):
        cmd.append("--zip_plots")
    if post_cfg.get("show_replicates", False):
        cmd.append("--show_replicates")

    dark = bool(post_cfg.get("dark", False)) or bool(args.dark)
    transparent = bool(post_cfg.get("transparent", False)) or bool(args.transparent)
    if dark:
        cmd.append("--dark")
    if transparent:
        cmd.append("--transparent")
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/dtag_config.yaml")
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--dark", action="store_true", help="Override config and make plots dark-background compatible")
    ap.add_argument("--transparent", action="store_true", help="Override config and save transparent plots")
    ap.add_argument("--print-command", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    cfg = load_config(config_path)
    root = package_root_for_config(config_path)
    exp = get_experiment(cfg, args.experiment)
    cmd = build_command(root, cfg, args.experiment, exp, args)

    print("COMMAND")
    print(" ".join(shlex.quote(x) for x in cmd))
    print()

    if args.print_command:
        return
    raise SystemExit(subprocess.call(cmd, cwd=str(root)))


if __name__ == "__main__":
    main()
