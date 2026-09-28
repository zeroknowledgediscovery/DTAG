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

Map discovery is conservative. It looks for filenames containing the ZA id
under maps/euromap/, maps/eurobarometer/, and maps/. If zero or multiple
candidates are found, pass --map explicitly.
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
    roots = [
        ROOT / "maps" / "euromap",
        ROOT / "maps" / "eurobarometer",
        ROOT / "maps",
    ]
    hits = []
    seen = set()
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
    return sorted(hits)


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
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(
            f"No map containing {za} was found. Pass --map /path/to/{za}_map.csv"
        )
    raise SystemExit(
        f"More than one map matched {za}; pass --map explicitly:\n  "
        + "\n  ".join(str(p) for p in hits)
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
            if len(maps) == 1:
                print(f"  map: {maps[0].relative_to(ROOT)}")
            elif len(maps) == 0:
                print("  map: MISSING")
            else:
                print("  map: AMBIGUOUS")
                for m in maps:
                    print(f"    {m.relative_to(ROOT)}")
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
