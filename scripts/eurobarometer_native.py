#!/usr/bin/env python3
"""Native-LSM Eurobarometer helpers: ZA normalisation, model/map resolution and run defaults.

Used by the web engine (Eurobarometer sessions take EUROBAROMETER_RUN_DEFAULTS,
DEFAULT_PERSONA and DEFAULT_CONTINENT from here). The former command-line launcher
(``--za ... --question ...``) is archived in archive/scripts/eurobarometer_native_cli.py.

Map resolution prefers a newly generated native per-ZA map, then an existing
legacy Eurobarometer per-ZA map. If neither exists, DTAG may use the legacy
integrated Eurobarometer fallback map. This lets waves with unavailable GESIS
variable reports remain runnable without pretending a fallback is an exact
wave-specific codebook.
"""
from __future__ import annotations

from pathlib import Path
from typing import List



ROOT = Path(__file__).resolve().parents[1]
from dtag_paths import model_path

MODEL_ROOT = model_path("eurobarometer")

DEFAULT_PERSONA = "45 year old adult, regular news consumer, politically attentive, moderate"
DEFAULT_CONTINENT = "Europe"

# Runtime parameters this launcher passes to pipeline_localized.py. The web
# engine reuses them so a Eurobarometer respondent behaves identically there.
EUROBAROMETER_RUN_DEFAULTS = {
    "state_keep": 500,
    "k": 6,
    "prefilter": 200,
    "min_map_score": 1.0,
    "semantic_fallback": "update_state",
    "semantic_k": 6,
    "semantic_prefilter": 80,
    "semantic_min_confidence": 0.35,
    "semantic_resp_mode": "max",
    "max_assign": 50,
    "assign_prefilter": 500,
    "resp_mode": "draw",
    "seed": 1000,
    "timing": True,
    "no_ideology": True,
}


def normalize_za(value: str) -> str:
    s = str(value).strip().upper()
    if not s:
        return ""
    if not s.startswith("ZA"):
        s = "ZA" + s
    return s


def model_dirs() -> List[Path]:
    if not MODEL_ROOT.is_dir():
        return []
    return sorted(
        p for p in MODEL_ROOT.iterdir()
        if p.is_dir() and p.name.upper().startswith("ZA")
    )


def valid_native_model(path: Path) -> bool:
    return (
        (path / "source_maps").is_dir()
        and (path / "trees" / "binary").is_dir()
    )


def map_candidates(za: str) -> List[Path]:
    """Return exact ZA-specific maps only, ordered by preferred source."""
    preferred = [
        ROOT / "maps" / "eurobarometer" / f"{za}_map.csv",
        ROOT / "maps" / "euromap" / f"eurobarometer_{za}_map.csv",
    ]

    hits: List[Path] = []
    seen = set()

    for p in preferred:
        if p.is_file():
            rp = p.resolve()
            hits.append(rp)
            seen.add(rp)

    # Compatibility discovery for any older naming convention containing ZA.
    roots = [
        ROOT / "maps" / "eurobarometer",
        ROOT / "maps" / "euromap",
        ROOT / "maps",
    ]
    for base in roots:
        if not base.exists():
            continue
        for p in base.rglob("*.csv"):
            if za.lower() not in p.name.lower():
                continue
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            hits.append(rp)

    return hits


def integrated_fallback_map() -> Path | None:
    candidates = [
        ROOT / "maps" / "euromap" / "eurobarometer_integrated_fallback_map.csv",
        ROOT / "maps" / "eurobarometer" / "eurobarometer_integrated_fallback_map.csv",
    ]
    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


def resolve_model(za: str) -> Path:
    direct = MODEL_ROOT / za
    if direct.is_dir():
        return direct.resolve()

    matches = [p for p in model_dirs() if p.name.upper().startswith(za)]
    if len(matches) == 1:
        return matches[0].resolve()
    if not matches:
        raise SystemExit(
            f"No native Eurobarometer model found for {za} under {MODEL_ROOT}"
        )
    raise SystemExit(
        f"Multiple model directories match {za}:\n  "
        + "\n  ".join(str(p) for p in matches)
    )


def resolve_map(za: str, explicit: str) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_absolute():
            p = ROOT / p
        p = p.resolve()
        if not p.is_file():
            raise SystemExit(f"Map does not exist: {p}")
        return p

    hits = map_candidates(za)
    if hits:
        # Deterministic precedence:
        #   1) newly generated native per-ZA map
        #   2) legacy per-ZA Eurobarometer map
        #   3) other exact ZA-named compatibility map
        chosen = hits[0]
        if len(hits) > 1:
            print(
                "MAP NOTE: multiple exact ZA maps found; using preferred "
                f"{chosen.relative_to(ROOT)}"
            )
        return chosen

    fallback = integrated_fallback_map()
    if fallback is not None:
        print(
            f"MAP FALLBACK: no exact {za} map; using "
            f"{fallback.relative_to(ROOT)}"
        )
        return fallback

    raise SystemExit(
        f"No exact map for {za} and no Eurobarometer integrated fallback map. "
        "Pass --map explicitly or generate maps/euromap/"
        "eurobarometer_integrated_fallback_map.csv."
    )
