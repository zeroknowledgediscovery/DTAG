#!/usr/bin/env python3
"""No-LLM regression test for deterministic DTAG country conditioning.

Default test: Afrobarometer R5 Nigeria versus Ghana. The test verifies that
country is hard-conditioned in the qnet initial state and that the two forced
state vectors differ only at the categorical country feature.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dtag_paths import model_path

import numpy as np
from model_backend import load_model

import pipeline as core
import pipeline_localized as localized


DTAG_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--qnet',
        default=str(model_path('afrobarometer', 'r5')),
    )
    ap.add_argument(
        '--model-backend',
        choices=['auto', 'native_lsm'],
        default='native_lsm',
    )
    ap.add_argument('--country-a', default='Nigeria')
    ap.add_argument('--country-b', default='Ghana')
    ap.add_argument('--assets-dir', default=str(DTAG_ROOT / 'assets'))
    args = ap.parse_args()

    model = load_model(args.qnet, backend=args.model_backend)
    feat = set(map(str, model.feature_names))
    idx_map = {str(v): i for i, v in enumerate(model.feature_names)}
    possible = core.get_possible_responses_cached(
        model, args.qnet, assets_dir=args.assets_dir
    )

    fa, ma = localized.build_forced_assignments(
        feat, possible, None, args.country_a, 'Africa'
    )
    fb, mb = localized.build_forced_assignments(
        feat, possible, None, args.country_b, 'Africa'
    )

    va = ma.get('categorical_country_feature')
    vb = mb.get('categorical_country_feature')
    if not va or not vb:
        raise SystemExit(
            f'FAIL: categorical country feature not found: {args.country_a}={va}, '
            f'{args.country_b}={vb}'
        )
    if va != vb:
        raise SystemExit(f'FAIL: countries resolved through different features: {va} vs {vb}')
    if fa.get(va) == fb.get(vb):
        raise SystemExit(f'FAIL: both countries resolved to the same value: {fa.get(va)!r}')

    xa = core.build_NULL_with_assignments(model, dict(fa), idx_map)
    xb = core.build_NULL_with_assignments(model, dict(fb), idx_map)
    diff = np.flatnonzero(xa != xb).tolist()
    expected_idx = idx_map[str(va)]
    if diff != [expected_idx]:
        raise SystemExit(
            f'FAIL: expected initial forced states to differ only at {va}; '
            f'differing indices={diff}'
        )

    print('PASS deterministic country conditioning')
    print(f'feature: {va}')
    print(f'{args.country_a}: {fa[va]}')
    print(f'{args.country_b}: {fb[vb]}')
    print(f'differing initial-state index: {expected_idx}')
    print(f'mode A: {ma.get("geography_conditioning_mode")}')
    print(f'mode B: {mb.get("geography_conditioning_mode")}')


if __name__ == '__main__':
    main()
