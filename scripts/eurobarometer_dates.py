#!/usr/bin/env python3
"""Eurobarometer fieldwork-date registry and resolver.

The registry file is the two-column table supplied for DTAG development:

    0078,31.01.1962 - 03.03.1962
    7575,09.05.2019 - 25.05.2019

No header is required. Partial dates such as MM.YYYY are supported.

Resolution policy is intentionally conservative:
- a full YYYY-MM-DD date may auto-select only when exactly one ordinary
  fieldwork interval covers it;
- if multiple waves cover the date, resolution is ambiguous and the caller
  must choose a ZA id explicitly;
- if no wave covers the date, no nearest wave is silently substituted;
- broad longitudinal/cumulative studies (>180 days) remain available by ZA
  but are excluded from automatic date selection.

This module does not use country coverage yet. Country-specific disambiguation
can be added when the separate Eurobarometer country/wave metadata is wired in.
"""
from __future__ import annotations

import calendar
import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class EurobarometerWave:
    za_id: str
    study_id: str
    raw_fieldwork: str
    start_date: date
    end_date: date
    start_precision: str
    end_precision: str
    auto_select: bool

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days


def normalize_za(value: str) -> str:
    s = str(value).strip().upper()
    if s.startswith("ZA"):
        s = s[2:]
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"Invalid Eurobarometer study id: {value!r}")
    return "ZA" + s.zfill(4)


def _parse_partial(value: str, *, end: bool) -> tuple[date, str]:
    s = str(value).strip()
    if not s:
        raise ValueError("empty partial date")

    parts = s.split(".")
    if len(parts) == 3:
        d, m, y = (int(x) for x in parts)
        return date(y, m, d), "day"

    if len(parts) == 2:
        m, y = (int(x) for x in parts)
        d = calendar.monthrange(y, m)[1] if end else 1
        return date(y, m, d), "month"

    if len(parts) == 1 and re.fullmatch(r"\d{4}", parts[0]):
        y = int(parts[0])
        return (date(y, 12, 31) if end else date(y, 1, 1)), "year"

    raise ValueError(f"Unsupported date format: {value!r}")


def _finish_from_start(start: date, precision: str) -> date:
    if precision == "day":
        return start
    if precision == "month":
        return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    if precision == "year":
        return date(start.year, 12, 31)
    raise ValueError(precision)


def parse_fieldwork(raw: str) -> tuple[date, date, str, str]:
    text = str(raw).strip()
    if "-" in text:
        left, right = text.split("-", 1)
    else:
        left, right = text, ""

    start, start_precision = _parse_partial(left.strip(), end=False)
    right = right.strip()
    if right:
        finish, end_precision = _parse_partial(right, end=True)
    else:
        finish = _finish_from_start(start, start_precision)
        end_precision = "inferred_from_start"

    if finish < start:
        raise ValueError(f"Fieldwork end precedes start: {raw!r}")
    return start, finish, start_precision, end_precision


def load_registry(path: str | Path) -> List[EurobarometerWave]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(p)

    rows: List[EurobarometerWave] = []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for line_no, row in enumerate(reader, 1):
            if not row or not any(str(x).strip() for x in row):
                continue
            if len(row) < 2:
                raise ValueError(f"{p}:{line_no}: expected two columns")

            study = str(row[0]).strip()
            raw = str(row[1]).strip()

            # Tolerate a descriptive header if one is added later.
            if line_no == 1 and not re.fullmatch(r"(?:ZA)?\d+", study, flags=re.I):
                continue

            za = normalize_za(study)
            start, finish, sp, ep = parse_fieldwork(raw)
            duration = (finish - start).days

            rows.append(
                EurobarometerWave(
                    za_id=za,
                    study_id=za[2:],
                    raw_fieldwork=raw,
                    start_date=start,
                    end_date=finish,
                    start_precision=sp,
                    end_precision=ep,
                    auto_select=(duration <= 180),
                )
            )

    seen = set()
    for wave in rows:
        if wave.za_id in seen:
            raise ValueError(f"Duplicate Eurobarometer study id in registry: {wave.za_id}")
        seen.add(wave.za_id)
    return rows


def waves_covering(
    waves: Iterable[EurobarometerWave],
    when: date,
    *,
    auto_only: bool = True,
) -> List[EurobarometerWave]:
    return [
        w for w in waves
        if (not auto_only or w.auto_select)
        and w.start_date <= when <= w.end_date
    ]


def waves_in_year(
    waves: Iterable[EurobarometerWave],
    year: int,
    *,
    auto_only: bool = True,
) -> List[EurobarometerWave]:
    lo, hi = date(year, 1, 1), date(year, 12, 31)
    return [
        w for w in waves
        if (not auto_only or w.auto_select)
        and w.start_date <= hi
        and w.end_date >= lo
    ]


def nearest_neighbors(
    waves: Iterable[EurobarometerWave],
    when: date,
    *,
    auto_only: bool = True,
) -> tuple[Optional[EurobarometerWave], Optional[EurobarometerWave]]:
    usable = [w for w in waves if not auto_only or w.auto_select]
    before = [w for w in usable if w.end_date < when]
    after = [w for w in usable if w.start_date > when]
    prev = max(before, key=lambda w: w.end_date) if before else None
    nxt = min(after, key=lambda w: w.start_date) if after else None
    return prev, nxt


def resolve_exact_date(
    waves: Iterable[EurobarometerWave],
    when: date,
) -> EurobarometerWave:
    hits = waves_covering(waves, when, auto_only=True)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        ids = ", ".join(
            f"{w.za_id} [{w.start_date}..{w.end_date}]" for w in hits
        )
        raise ValueError(
            f"Eurobarometer date {when.isoformat()} is ambiguous: {ids}. "
            "Specify --za explicitly."
        )

    prev, nxt = nearest_neighbors(waves, when, auto_only=True)
    context = []
    if prev:
        context.append(f"previous={prev.za_id} [{prev.start_date}..{prev.end_date}]")
    if nxt:
        context.append(f"next={nxt.za_id} [{nxt.start_date}..{nxt.end_date}]")
    suffix = "; " + "; ".join(context) if context else ""
    raise ValueError(
        f"No Eurobarometer fieldwork interval covers {when.isoformat()}{suffix}. "
        "Specify --za explicitly rather than silently using a nearest wave."
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Resolve Eurobarometer ZA studies from fieldwork dates")
    ap.add_argument("--dates-file", default="configs/eurodates.csv")
    ap.add_argument("--date", default="", help="full calendar date YYYY-MM-DD")
    ap.add_argument("--year", type=int, default=None, help="list all waves overlapping a year")
    ap.add_argument("--za", default="", help="show one ZA registry row")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    p = Path(args.dates_file).expanduser()
    if not p.is_absolute():
        p = (root / p).resolve()

    waves = load_registry(p)

    if args.za:
        za = normalize_za(args.za)
        hits = [w for w in waves if w.za_id == za]
        if not hits:
            raise SystemExit(f"{za} not found in {p}")
        w = hits[0]
        print(
            f"{w.za_id}: {w.start_date} .. {w.end_date} "
            f"raw={w.raw_fieldwork!r} auto_select={w.auto_select}"
        )
        return

    if args.date:
        try:
            when = date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit("--date must use YYYY-MM-DD")
        try:
            w = resolve_exact_date(waves, when)
        except ValueError as e:
            raise SystemExit(str(e))
        print(
            f"{when.isoformat()} -> {w.za_id} "
            f"[{w.start_date} .. {w.end_date}]"
        )
        return

    if args.year is not None:
        hits = waves_in_year(waves, args.year)
        for w in hits:
            print(f"{w.za_id}: {w.start_date} .. {w.end_date}")
        print(f"{len(hits)} wave(s) overlap {args.year}")
        return

    print(f"Loaded {len(waves)} Eurobarometer fieldwork rows from {p}")
    broad = [w for w in waves if not w.auto_select]
    if broad:
        print("Excluded from automatic date selection:")
        for w in broad:
            print(f"  {w.za_id}: {w.start_date} .. {w.end_date}")


if __name__ == "__main__":
    main()
