#!/usr/bin/env python3
"""DTAG configuration profiles (configs/dtag_config.yaml).

Loads the config and resolves a named interactive profile into concrete runtime settings
(model, map, persona, geography, run parameters) with the defaults < profile < override
precedence. Used by the web engine (dtag_engine.DTAGEngine).

These functions were moved verbatim from the former command-line launcher interactive.py
(now in archive/scripts/).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from dtag_paths import resolve_repo_path


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
