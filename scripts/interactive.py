#!/usr/bin/env python3
"""Config-driven interactive DTAG launcher.

Examples:
  python3 scripts/interactive.py --list
  python3 scripts/interactive.py --profile afrobarometer_r5_nigeria
  python3 scripts/interactive.py --profile wvs7_india_2017 --question "Do you trust government?"
  python3 scripts/interactive.py --profile gss2022_wf --autoplay_csv assets/question_sets/smoke/long_gss_smoke.csv

If neither --question nor --autoplay_csv is supplied, loop mode is used.
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

from dtag_paths import resolve_repo_path


VALUE_FLAGS = {
    'state_keep': '--state_keep',
    'k': '--k',
    'prefilter': '--prefilter',
    'min_map_score': '--min_map_score',
    'semantic_fallback': '--semantic_fallback',
    'semantic_k': '--semantic_k',
    'semantic_prefilter': '--semantic_prefilter',
    'semantic_min_confidence': '--semantic_min_confidence',
    'semantic_embedding_model': '--semantic_embedding_model',
    'semantic_resp_mode': '--semantic_resp_mode',
    'max_assign': '--max_assign',
    'assign_prefilter': '--assign_prefilter',
    'resp_mode': '--resp_mode',
    'openai_model': '--openai_model',
    'seed': '--seed',
}

BOOL_FLAGS = {
    'timing': '--timing',
    'no_ideology': '--no_ideology',
    'require_polar_vectors': '--require_polar_vectors',
}


def load_config(path: Path) -> Dict[str, Any]:
    obj = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise SystemExit(f'Config must be a mapping: {path}')
    return obj


def resolve_named(cfg: Dict[str, Any], section: str, value: str) -> str:
    table = cfg.get(section, {}) or {}
    if isinstance(table, dict) and value in table:
        return str(table[value])
    return value


def optional_text(value: Any) -> str:
    if value is None:
        return ''
    s = str(value).strip()
    if s.lower() in {'', 'none', 'null', 'false', 'off', 'disabled'}:
        return ''
    return s


def config_root(config_path: Path) -> Path:
    config_path = Path(config_path).expanduser().resolve()
    return config_path.parent.parent if config_path.parent.name == 'configs' else config_path.parent


def resolve_profile(
    cfg: Dict[str, Any],
    profile_name: str,
    root: Path,
    semantic_fallback: str = '',
    persona: Any = None,
    country: Any = None,
    continent: Any = None,
    year: Any = None,
    no_ideology: bool = False,
    with_ideology: bool = False,
) -> Dict[str, Any]:
    """Resolve an interactive profile into concrete runtime settings.

    Shared by the command-line launcher and the DTAG web engine so both apply
    identical defaults/profile/override precedence.
    """
    profiles = cfg.get('interactive_profiles', {}) or {}
    if profile_name not in profiles:
        raise SystemExit(f'Unknown profile {profile_name!r}. Use --list.')
    profile = dict(profiles[profile_name] or {})

    defaults = cfg.get('defaults', {}) or {}
    run_cfg = dict(defaults.get('run', {}) or {})
    run_cfg.update(profile.get('run', {}) or {})

    # Interactive runs should be deterministic by default unless the profile opts out.
    if 'resp_mode' not in (profile.get('run', {}) or {}):
        run_cfg['resp_mode'] = 'max'
    if 'seed' not in run_cfg and 'seed_base' in run_cfg:
        run_cfg['seed'] = run_cfg['seed_base']
    if semantic_fallback:
        run_cfg['semantic_fallback'] = semantic_fallback

    qnet_ref = str(profile.get('qnet', ''))
    map_ref = str(profile.get('map', ''))
    qnet = resolve_named(cfg, 'models', qnet_ref)
    map_path = resolve_named(cfg, 'maps', map_ref)
    persona = persona if persona is not None else str(profile.get('persona', ''))
    if not qnet or not map_path or not persona:
        raise SystemExit(f'Profile {profile_name!r} must define qnet, map, and persona')

    polar = optional_text(profile.get('polar_vectors', defaults.get('polar_vectors', '')))
    if no_ideology:
        run_cfg['no_ideology'] = True
    if with_ideology:
        run_cfg['no_ideology'] = False

    return {
        'name': profile_name,
        'description': str(profile.get('description', '')).strip(),
        'pipeline': str(profile.get('pipeline', defaults.get('pipeline', 'scripts/pipeline_localized.py'))),
        'qnet_ref': qnet_ref,
        'map_ref': map_ref,
        'qnet': qnet,
        'qnet_path': resolve_repo_path(qnet, root),
        'map': map_path,
        'map_path': resolve_repo_path(map_path, root),
        'persona': persona,
        'country': country if country is not None else str(profile.get('country', '')),
        'continent': continent if continent is not None else str(profile.get('continent', '')),
        'year': year if year is not None else profile.get('year'),
        'polar_vectors': polar,
        'assets_dir': str(profile.get('assets_dir', 'assets')),
        'logs_dir': str(profile.get('logs_dir', f'outputs/interactive_{profile_name}')),
        'tag': str(profile.get('tag', profile_name)),
        'run': run_cfg,
    }


def build_command(
    cfg: Dict[str, Any],
    profile_name: str,
    args: argparse.Namespace,
) -> tuple[List[str], Path]:
    root = config_root(Path(args.config))
    r = resolve_profile(
        cfg,
        profile_name,
        root,
        semantic_fallback=args.semantic_fallback,
        persona=args.persona,
        country=args.country,
        continent=args.continent,
        year=args.year,
        no_ideology=args.no_ideology,
        with_ideology=args.with_ideology,
    )
    run_cfg = r['run']

    py = str(run_cfg.get('python', sys.executable or 'python3'))
    qnet_check = r['qnet_path']
    if not qnet_check.exists():
        raise SystemExit(
            f"Profile {profile_name!r} model is not available yet: {qnet_check}. "
            "Install it with dtag-models, for example: "
            f"dtag-models {r['qnet'].split('models/lsm/', 1)[-1]}"
        )

    logs_dir = args.logs_dir or r['logs_dir']
    tag = args.tag or r['tag']

    cmd: List[str] = [py, r['pipeline'], '--map', r['map'], '--qnet', str(qnet_check), '--persona', r['persona']]
    cmd += ['--assets_dir', r['assets_dir']]
    cmd += ['--logs_dir', logs_dir, '--tag', tag]

    if r['year'] is not None:
        cmd += ['--year', str(r['year'])]
    if r['country']:
        cmd += ['--country', r['country']]
    if r['continent']:
        cmd += ['--continent', r['continent']]
    if r['polar_vectors']:
        cmd += ['--polar_vectors', r['polar_vectors']]

    for key, flag in VALUE_FLAGS.items():
        if key in run_cfg and run_cfg[key] is not None:
            cmd += [flag, str(run_cfg[key])]
    for key, flag in BOOL_FLAGS.items():
        if bool(run_cfg.get(key, False)):
            cmd.append(flag)

    if args.autoplay_csv:
        cmd += ['--autoplay_csv', args.autoplay_csv]
    elif args.question:
        cmd += ['--question', args.question]
    else:
        cmd.append('--loop')

    return cmd, root.resolve()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='configs/dtag_config.yaml')
    ap.add_argument('--profile', default='')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--question', default='')
    ap.add_argument('--autoplay_csv', default='')
    ap.add_argument('--persona', default=None)
    ap.add_argument('--country', default=None)
    ap.add_argument('--continent', default=None)
    ap.add_argument('--year', type=int, default=None)
    ap.add_argument('--logs_dir', default='')
    ap.add_argument('--tag', default='')
    ap.add_argument('--semantic_fallback', choices=['off', 'answer_only', 'update_state'], default='')
    ideology = ap.add_mutually_exclusive_group()
    ideology.add_argument('--no_ideology', action='store_true')
    ideology.add_argument('--with_ideology', action='store_true')
    ap.add_argument('--print-command', action='store_true')
    args = ap.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    cfg = load_config(config_path)
    profiles = cfg.get('interactive_profiles', {}) or {}

    if args.list:
        print('Available interactive profiles:')
        root = config_path.parent.parent if config_path.parent.name == 'configs' else config_path.parent
        for name in sorted(profiles):
            spec = profiles[name] or {}
            desc = str(spec.get('description', '')).strip()
            qkey = str(spec.get('qnet', ''))
            qpath = resolve_named(cfg, 'models', qkey) if qkey else ''
            status = ''
            if qpath:
                p = resolve_repo_path(qpath, root)
                if not p.exists():
                    status = ' [model not installed]'
            print(f'  {name}{status}' + (f' - {desc}' if desc else ''))
        return

    if not args.profile:
        raise SystemExit('Provide --profile, or use --list')
    if args.question and args.autoplay_csv:
        raise SystemExit('Use only one of --question or --autoplay_csv')

    cmd, root = build_command(cfg, args.profile, args)
    if args.print_command:
        print(shlex.join(cmd))
        return

    raise SystemExit(subprocess.call(cmd, cwd=root))


if __name__ == '__main__':
    main()
