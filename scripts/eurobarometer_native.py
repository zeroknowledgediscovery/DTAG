#!/usr/bin/env python3
"""Run a native-LSM Eurobarometer wave by explicit ZA identifier.

This is the development bridge before date->wave routing is implemented.
It deliberately requires an explicit ZA wave so DTAG never guesses which
Eurobarometer model corresponds to a requested date.

Examples:
  python3 scripts/eurobarometer_native.py --list
  python3 scripts/eurobarometer_native.py --za ZA7575 --country France
  python3 scripts/eurobarometer_native.py --za ZA7575 --country France \
      --question "How satisfied are you with democracy?"

Map resolution prefers a newly generated native per-ZA map, then an existing
legacy Eurobarometer per-ZA map. If neither exists, DTAG may use the legacy
integrated Eurobarometer fallback map. This lets waves with unavailable GESIS
variable reports remain runnable without pretending a fallback is an exact
wave-specific codebook.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List

from eurobarometer_dates import (
    load_registry,
    resolve_exact_date,
    waves_in_year,
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / "lsm" / "eurobarometer"


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list discovered ZA models/maps")
    ap.add_argument("--za", default="", help="Eurobarometer ZA identifier")
    ap.add_argument("--date", default="", help="Resolve ZA from exact fieldwork date YYYY-MM-DD")
    ap.add_argument("--dates-file", default="configs/eurodates.csv", help="two-column ZA/date registry")
    ap.add_argument("--map", default="", help="explicit map CSV; otherwise conservative ZA discovery")
    ap.add_argument(
        "--persona",
        default="45 year old adult, regular news consumer, politically attentive, moderate",
    )
    ap.add_argument("--country", default="")
    ap.add_argument("--continent", default="Europe")
    ap.add_argument("--year", type=int, default=None, help="context/conditioning; if no --za/--date is given, list candidate waves in that year")
    ap.add_argument("--question", default="")
    ap.add_argument("--logs-dir", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--semantic-fallback", choices=["off", "answer_only", "update_state"], default="answer_only")
    ap.add_argument("--resp-mode", choices=["max", "draw"], default="max")
    ap.add_argument("--state-keep", type=int, default=500)
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--prefilter", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--print-command", action="store_true")
    args = ap.parse_args()

    if args.list:
        rows = []
        for p in model_dirs():
            za = p.name.split("_")[0].upper()
            maps = map_candidates(za)
            rows.append((p.name, "OK" if valid_native_model(p) else "INVALID", maps))
        if not rows:
            print(f"No Eurobarometer models found under {MODEL_ROOT}")
            return
        for name, status, maps in rows:
            print(f"{name}: {status}")
            if maps:
                print(f"  map: {maps[0].relative_to(ROOT)}")
                if len(maps) > 1:
                    print(f"  alternatives: {len(maps) - 1}")
            else:
                fb = integrated_fallback_map()
                if fb is not None:
                    print(f"  map: FALLBACK -> {fb.relative_to(ROOT)}")
                else:
                    print("  map: MISSING")
        return

    dates_path = Path(args.dates_file).expanduser()
    if not dates_path.is_absolute():
        dates_path = (ROOT / dates_path).resolve()

    za = ""
    if args.za:
        za = normalize_za(args.za)
    elif args.date:
        try:
            when = date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit("--date must use YYYY-MM-DD")
        try:
            waves = load_registry(dates_path)
            wave = resolve_exact_date(waves, when)
        except Exception as e:
            raise SystemExit(str(e))
        za = wave.za_id
        print(
            f"DATE RESOLUTION: {when.isoformat()} -> {wave.za_id} "
            f"[{wave.start_date} .. {wave.end_date}]"
        )
    elif args.year is not None:
        try:
            waves = load_registry(dates_path)
            candidates = waves_in_year(waves, args.year)
        except Exception as e:
            raise SystemExit(str(e))
        if not candidates:
            raise SystemExit(f"No Eurobarometer fieldwork rows overlap {args.year}")
        print(f"Eurobarometer waves overlapping {args.year}:")
        for w in candidates:
            installed = any(p.name.upper().startswith(w.za_id) for p in model_dirs())
            suffix = " [model installed]" if installed else ""
            print(f"  {w.za_id}: {w.start_date} .. {w.end_date}{suffix}")
        raise SystemExit(
            "Year alone is not sufficient to select one Eurobarometer wave. "
            "Use --date YYYY-MM-DD or --za ZAxxxx."
        )
    else:
        raise SystemExit("--za or --date is required unless --list is used")

    model = resolve_model(za)
    if not valid_native_model(model):
        raise SystemExit(
            f"Model directory is incomplete: {model}\n"
            "Expected source_maps/ and trees/binary/."
        )
    map_path = resolve_map(za, args.map)

    logs_dir = args.logs_dir or f"outputs/interactive_eurobarometer_{za}"
    tag = args.tag or f"Eurobarometer_{za}_interactive"

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pipeline_localized.py"),
        "--qnet", str(model),
        "--model_backend", "native_lsm",
        "--map", str(map_path),
        "--persona", args.persona,
        "--assets_dir", str(ROOT / "assets"),
        "--logs_dir", str(ROOT / logs_dir),
        "--tag", tag,
        "--continent", args.continent,
        "--state_keep", str(args.state_keep),
        "--k", str(args.k),
        "--prefilter", str(args.prefilter),
        "--min_map_score", "1.0",
        "--semantic_fallback", args.semantic_fallback,
        "--semantic_k", "6",
        "--semantic_prefilter", "80",
        "--semantic_min_confidence", "0.35",
        "--semantic_resp_mode", "max",
        "--max_assign", "50",
        "--assign_prefilter", "500",
        "--resp_mode", args.resp_mode,
        "--seed", str(args.seed),
        "--timing",
        "--no_ideology",
    ]
    if args.country:
        cmd += ["--country", args.country]
    if args.year is not None:
        cmd += ["--year", str(args.year)]
    if args.question:
        cmd += ["--question", args.question]
    else:
        cmd += ["--loop"]

    if args.date:
        print("ZA model selected from exact fieldwork-date coverage.")
    else:
        print("ZA model selection is explicit; --year alone never selects a Eurobarometer wave.")
    print("MODEL:", model)
    print("MAP:  ", map_path)
    print("CMD:  ", " ".join(map(str, cmd)))
    if args.print_command:
        return
    raise SystemExit(subprocess.call(cmd, cwd=ROOT))


if __name__ == "__main__":
    main()
