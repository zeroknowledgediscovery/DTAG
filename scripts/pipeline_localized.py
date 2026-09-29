#!/usr/bin/env python3
"""Canonical DTAG pipeline entry point with deterministic geographic conditioning.

This module wraps ``pipeline.py`` rather than duplicating it. It replaces only
``build_forced_assignments`` before calling the core main function.

Country conditioning order:
1. If a qnet has a categorical country feature whose allowed support contains the
   requested country, hard-condition that feature directly.
2. Otherwise use the legacy WVS-style O1_LONGITUDE/O2_LATITUDE proxy forcing.
3. If neither representation exists, keep the request in metadata/persona context
   and emit a warning rather than inventing a country state.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from typing import Dict, List, Optional, Set, Tuple

import pipeline as core


_ORIGINAL_BUILD_FORCED_ASSIGNMENTS = core.build_forced_assignments


def _canonical_country_targets(country: str) -> Set[str]:
    key = core._canonicalize_place_name(country)
    out = {key}
    canonical = core.COUNTRY_ALIASES.get(key)
    if canonical:
        out.add(core._canonicalize_place_name(canonical))
    return {x for x in out if x}


def _country_feature_priority(variable: str) -> Tuple[int, str]:
    raw = str(variable)
    key = raw.upper().replace('-', '_').replace(' ', '_')
    preferred = [
        'COUNTRY_ALPHA',
        'COUNTRY',
        'COUNTRY_R7LIST',
        'COUNTRY_R6LIST',
        'COUNTRY_R5LIST',
        'COUNTRY_OLD.ORDER',
        'COUNTRY_OLD_ORDER',
        'COUNTRY.OLD.SPELLING',
        'COUNTRY_OLD_SPELLING',
    ]
    if key in preferred:
        return preferred.index(key), raw
    low = raw.lower()
    if 'country' in low and 'region' not in low:
        return 100, raw
    return 1000, raw


def find_categorical_country_assignment(
    feat: Set[str],
    possible: Dict[str, List[str]],
    requested_country: str,
) -> Tuple[Optional[str], Optional[str]]:
    targets = _canonical_country_targets(requested_country)
    if not targets:
        return None, None

    candidates = [
        str(v) for v in feat
        if 'country' in str(v).lower() and 'region' not in str(v).lower()
    ]
    candidates.sort(key=_country_feature_priority)

    for var in candidates:
        for value in possible.get(var, []):
            if core._canonicalize_place_name(value) in targets:
                return var, str(value)

    # Some survey exports truncate long labels (for example "South Afri").
    # Permit a conservative long-prefix match only after exact matching fails.
    for var in candidates:
        for value in possible.get(var, []):
            cv = core._canonicalize_place_name(value)
            if len(cv) < 8:
                continue
            for target in targets:
                if target.startswith(cv) or cv.startswith(target):
                    return var, str(value)

    # Eurobarometer-style labels carry an ISO code prefix and sometimes a
    # parenthetical ("FR - France", "CY - Cyprus (Republic)", "ES -Spain").
    # Match the country-name part exactly, and only when a single support
    # value within the feature matches (e.g. "Germany" never picks one of
    # "DE-W - Germany West" / "DE-E - Germany East").
    for var in candidates:
        hits = []
        for value in possible.get(var, []):
            raw = str(value)
            if '-' not in raw:
                continue
            name = raw.rsplit('-', 1)[1]
            name = re.sub(r'\([^)]*\)', ' ', name)
            name = re.sub(r'^\s*the\s+', '', name, flags=re.I)  # "NL - The Netherlands"
            if core._canonicalize_place_name(name) in targets:
                hits.append(raw)
        if len(hits) == 1:
            return var, hits[0]

    return None, None


def build_forced_assignments(
    feat: Set[str],
    possible: Dict[str, List[str]],
    year: Optional[int],
    country: str,
    continent: str,
):
    if country:
        country_var, country_value = find_categorical_country_assignment(
            feat=feat,
            possible=possible,
            requested_country=country,
        )
        if country_var is not None and country_value is not None:
            # Preserve year forcing, but do not add coordinate proxies when a
            # direct categorical country state exists.
            forced, meta = _ORIGINAL_BUILD_FORCED_ASSIGNMENTS(
                feat=feat,
                possible=possible,
                year=year,
                country='',
                continent='',
            )
            forced = OrderedDict(forced)
            forced[country_var] = country_value

            meta['requested_country'] = country
            meta['requested_continent'] = continent or None
            meta['resolved_country_key'] = core._canonicalize_place_name(country)
            meta['resolved_continent_key'] = (
                core._canonicalize_place_name(continent) if continent else None
            )
            meta['geography_conditioning_mode'] = 'categorical_country'
            meta['categorical_country_feature'] = country_var
            meta['categorical_country_value'] = country_value
            meta['hard_conditioned_country'] = True
            meta.pop('geography_warning', None)
            return forced, meta

    try:
        forced, meta = _ORIGINAL_BUILD_FORCED_ASSIGNMENTS(
            feat=feat,
            possible=possible,
            year=year,
            country=country,
            continent=continent,
        )
    except ValueError as exc:
        # A country may be valid in survey categorical support even if it is not
        # in the legacy coordinate table. If no direct country feature matched,
        # preserve year/continent forcing and record the limitation.
        forced, meta = _ORIGINAL_BUILD_FORCED_ASSIGNMENTS(
            feat=feat,
            possible=possible,
            year=year,
            country='',
            continent=continent,
        )
        meta['requested_country'] = country or None
        meta['resolved_country_key'] = (
            core._canonicalize_place_name(country) if country else None
        )
        meta['hard_conditioned_country'] = False
        meta['country_warning'] = str(exc)

    if country:
        if 'O1_LONGITUDE' in forced and 'O2_LATITUDE' in forced:
            meta['geography_conditioning_mode'] = 'coordinate_proxy'
            meta['hard_conditioned_country'] = True
        else:
            meta.setdefault('geography_conditioning_mode', 'context_only')
            meta.setdefault('hard_conditioned_country', False)
    return forced, meta


core.build_forced_assignments = build_forced_assignments


if __name__ == '__main__':
    core.main()
