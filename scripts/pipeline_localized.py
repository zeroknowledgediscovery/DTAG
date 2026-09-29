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


# ISO 3166 alpha-2 codes used by Eurobarometer ``isocntry`` variables
# ("COUNTRY CODE - ISO 3166"). Sub-national samples (DE-E/DE-W, GB-GBN/GB-NIR,
# CY-TCC) map to their own names so a plain "Germany" never picks one half.
ISO_COUNTRY_NAMES: Dict[str, str] = {
    'AL': 'albania', 'AT': 'austria', 'BA': 'bosnia and herzegovina', 'BE': 'belgium',
    'BG': 'bulgaria', 'CH': 'switzerland', 'CY': 'cyprus', 'CY-TCC': 'cyprus tcc',
    'CZ': 'czechia', 'DE': 'germany', 'DE-E': 'east germany', 'DE-W': 'west germany',
    'DK': 'denmark', 'EE': 'estonia', 'ES': 'spain', 'FI': 'finland', 'FR': 'france',
    'GB': 'united kingdom', 'GB-GBN': 'great britain', 'GB-NIR': 'northern ireland',
    'GR': 'greece', 'EL': 'greece', 'HR': 'croatia', 'HU': 'hungary', 'IE': 'ireland',
    'IS': 'iceland', 'IT': 'italy', 'LT': 'lithuania', 'LU': 'luxembourg', 'LV': 'latvia',
    'ME': 'montenegro', 'MK': 'north macedonia', 'MT': 'malta', 'NL': 'netherlands',
    'NO': 'norway', 'PL': 'poland', 'PT': 'portugal', 'RO': 'romania', 'RS': 'serbia',
    'RS-KM': 'kosovo', 'XK': 'kosovo', 'SE': 'sweden', 'SI': 'slovenia', 'SK': 'slovakia',
    'TR': 'turkey', 'UK': 'united kingdom',
}

# Native-language / variant spellings seen in older Eurobarometer NATION
# variables, mapped to the English names used for matching.
COUNTRY_VALUE_ALIASES: Dict[str, str] = {
    'deutschland': 'germany', 'belgique': 'belgium', 'nederland': 'netherlands',
    'the netherlands': 'netherlands', 'irleand': 'ireland', 'rep of cyprus': 'cyprus',
    'northern ieland': 'northern ireland', 'northireland': 'northern ireland',
    'nothern ireland': 'northern ireland', 'czech republic': 'czechia',
    'macedonia': 'north macedonia', 'germany east': 'east germany',
    'germany west': 'west germany', 'britain': 'great britain',
}


def _value_country_name(value: str) -> str:
    """English canonical name for a support value (ISO code or label)."""
    raw = str(value).strip()
    if raw.upper() in ISO_COUNTRY_NAMES:
        return ISO_COUNTRY_NAMES[raw.upper()]
    name = re.sub(r'\([^)]*\)', ' ', raw)
    name = core._canonicalize_place_name(name)
    return COUNTRY_VALUE_ALIASES.get(name, name)


def find_categorical_country_assignment(
    feat: Set[str],
    possible: Dict[str, List[str]],
    requested_country: str,
    hint_features: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Find the model variable/value that hard-conditions ``requested_country``.

    Passes 1-3 are the original matcher over variables named "country".
    Only if they find nothing, two further passes apply, each accepting a
    value only when it is the unique match within its variable:

    4. ISO 3166 code variables (Eurobarometer ``isocntry``);
    5. ``hint_features`` -- variables the semantic map labels as the nation
       variable (older Eurobarometer ``NATION``), plus native/variant spellings.
    """
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

    wanted = {COUNTRY_VALUE_ALIASES.get(t, t) for t in targets}
    extra = [v for v in sorted(feat) if v.lower() == 'isocntry']
    extra += [v for v in (hint_features or []) if v in feat and v not in extra]
    for var in extra:
        vals = possible.get(var, [])
        if len(vals) < 3:
            continue
        hits = [str(x) for x in vals if _value_country_name(x) in wanted]
        if len(hits) == 1:
            return var, hits[0]

    return None, None


def build_forced_assignments(
    feat: Set[str],
    possible: Dict[str, List[str]],
    year: Optional[int],
    country: str,
    continent: str,
    hint_features: Optional[List[str]] = None,
):
    if country:
        country_var, country_value = find_categorical_country_assignment(
            feat=feat,
            possible=possible,
            requested_country=country,
            hint_features=hint_features,
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
