#!/usr/bin/env python3
"""Choose a native DTAG model from a respondent's description, country and time.

The recommender answers "which native survey model should represent this
respondent?" before anything is downloaded. It uses:

* ``configs/model_coverage.json`` -- per-model country support and year
  features, generated from the models' own source maps
  (``scripts/build_model_coverage.py``);
* the catalog (public manifest + installed models);
* the Eurobarometer fieldwork registry (``configs/eurodates.csv``);
* the same categorical-country matcher the pipeline uses to hard-condition
  country (``pipeline_localized.find_categorical_country_assignment``), so a
  recommendation of "categorical country" means the LSM *will* be conditioned.

For each survey family it proposes the best-fitting model, ranks the families,
and marks a default. Ranking: time fit first (within a year > within three years > further), then the
strength of geographic conditioning (categorical country > national survey >
country present but contextual only > coordinate proxy), then recency.

It never changes inference; it only produces a model key plus the exact
overrides (year/date/ZA) to create the session with.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pipeline as core
import pipeline_localized as localized

REPO_ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = REPO_ROOT / "configs" / "model_coverage.json"

# Approximate Afrobarometer round fieldwork periods (published round
# descriptions). The native Afrobarometer models carry no date variable, so
# these periods are the only time information for round selection.
AFRO_ROUND_YEARS: Dict[str, Tuple[int, int]] = {
    "r1": (1999, 2001), "r2": (2002, 2004), "r3": (2005, 2006),
    "r4": (2008, 2009), "r5": (2011, 2013), "r6": (2014, 2015),
    "r7": (2016, 2018), "r8": (2019, 2021), "r9": (2021, 2023),
}

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "chicago", "los angeles",
    "san francisco", "houston", "boston", "seattle", "atlanta", "miami", "detroit", "philadelphia",
]
# "georgia" and "washington" are ambiguous (country / US state); they count as
# the US only in "<state>, usa"-free text when no other country is detected.
AMBIGUOUS_US = {"georgia", "washington"}

ALIASES = {
    "usa": "united states", "us": "united states", "u s": "united states", "u s a": "united states",
    "america": "united states", "united states of america": "united states", "american": "united states",
    "uk": "united kingdom", "britain": "united kingdom", "great britain": "united kingdom",
    "england": "united kingdom", "scotland": "united kingdom", "wales": "united kingdom",
    "deutschland": "germany", "belgique": "belgium", "nederland": "netherlands", "holland": "netherlands",
    "irleand": "ireland", "northern ieland": "northern ireland", "northireland": "northern ireland",
    "nothern ireland": "northern ireland", "rep of cyprus": "cyprus", "cyprus republic": "cyprus",
    "cabo verde": "cape verde", "swaziland": "eswatini", "czech republic": "czechia",
    "macedonia": "north macedonia", "makedonia fyrom": "north macedonia", "macedonia fyrom": "north macedonia",
    "fyrom": "north macedonia", "cote divoire": "cote d ivoire", "ivory coast": "cote d ivoire",
    "the gambia": "gambia", "gambia the": "gambia", "south korea": "south korea", "korea": "south korea",
    "russian federation": "russia",
}
# Labels that denote part of a country (coverage only: never a unique match).
PARTIAL = {
    "germany east": "germany", "germany west": "germany", "east germany": "germany",
    "west germany": "germany", "cyprus tcc": "cyprus", "cy tcc": "cyprus",
}
FAMILY_LABEL = {"gss": "GSS", "afrobarometer": "Afrobarometer", "wvs": "World Values Survey 7", "eurobarometer": "Eurobarometer"}

GEO_STRENGTH = {"categorical": 3.0, "national_survey": 2.5, "coverage_only": 1.5, "coordinates": 1.0, "assumed": 0.5}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_country(label: str) -> str:
    """Canonical country key for a survey label or user input."""
    s = _strip_accents(str(label or "")).replace("’", "'")
    s = re.sub(r"^[A-Z]{2}(?:-[A-Z]{1,4})?(?=\s|\s*-\s)\s*-?\s*", "", s)  # "FR - France", "GB-UKM - ..."
    s = re.sub(r"\([^)]*\)", " ", s)
    s = core._canonicalize_place_name(s)
    s = re.sub(r"^the\s+", "", s).strip()
    s = s.replace("-", " ")
    return ALIASES.get(s, s)


def _label_key(label: str) -> Tuple[str, bool]:
    k = norm_country(label)
    if k in PARTIAL:
        return PARTIAL[k], True
    return k, False


def load_coverage(path: Path = COVERAGE_PATH) -> Dict[str, Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("models", {})
    except Exception:
        return {}


@dataclass
class Candidate:
    model_key: str
    family: str
    label: str
    geo_mode: str
    geo_note: str
    time_mode: str
    time_note: str
    time_distance: float
    recency: float
    overrides: Dict[str, Any] = field(default_factory=dict)
    conditioned_value: Optional[str] = None

    @property
    def time_bucket(self) -> int:
        # Within a year counts as a good fit (GSS runs biennially); beyond
        # three years the survey is clearly from another period.
        if self.time_distance <= 1:
            return 0
        return 1 if self.time_distance <= 3 else 2

    def sort_key(self):
        return (self.time_bucket, -GEO_STRENGTH.get(self.geo_mode, 0), self.time_distance, -self.recency)


class Recommender:
    def __init__(self, engine: Any):
        self.engine = engine
        self._coverage: Optional[Dict[str, Dict[str, Any]]] = None
        self._index: Optional[Dict[str, Dict[str, Any]]] = None

    # -- data --------------------------------------------------------------

    @property
    def coverage(self) -> Dict[str, Dict[str, Any]]:
        if self._coverage is None:
            self._coverage = load_coverage()
        return self._coverage

    def country_index(self) -> Dict[str, Dict[str, Any]]:
        """country key -> {name, families, models} (name = display form)."""
        if self._index is not None:
            return self._index
        idx: Dict[str, Dict[str, Any]] = {}

        def add(key: str, name: str, fam: Optional[str]) -> None:
            if not key:
                return
            rec = idx.setdefault(key, {"name": name, "families": set()})
            if fam:
                rec["families"].add(fam)

        for k in self.coverage:
            fam = k.split("/", 1)[0]
            possible, _ = self._country_support(k)
            for lab in (x for vals in possible.values() for x in vals):
                lab = str(lab).strip()
                if lab.isdigit() or lab.lower() in {"none", "nan", ""}:
                    continue
                if lab.upper() in localized.ISO_COUNTRY_NAMES:
                    lab = localized.ISO_COUNTRY_NAMES[lab.upper()]
                key, _ = _label_key(lab)
                add(key, key.title(), fam)
        add("united states", "United States", "gss")
        for c in core.list_supported_countries():
            key = norm_country(c)
            add(key, key.title(), "wvs" if self._wvs_covers(key) else None)
        for rec in idx.values():
            rec["families"] = sorted(rec["families"])
        self._index = idx
        return idx

    # -- detection -----------------------------------------------------------

    def detect(self, persona: str) -> Dict[str, Any]:
        """Deterministically detect country and survey year in a description."""
        text = " " + _strip_accents(str(persona or "")).lower() + " "
        out: Dict[str, Any] = {"country": None, "country_evidence": None, "year": None, "year_evidence": None}
        names: List[Tuple[str, str]] = []
        for key in self.country_index():
            names.append((key, key))
        for alias, key in ALIASES.items():
            if len(alias) > 2:
                names.append((alias, key))
        names.sort(key=lambda t: -len(t[0]))
        for phrase, key in names:
            if phrase in AMBIGUOUS_US:
                continue
            if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text):
                out["country"], out["country_evidence"] = self.country_index().get(key, {"name": key.title()})["name"], phrase
                break
        if out["country"] is None:
            for st in sorted(US_STATES, key=len, reverse=True):
                if re.search(rf"(?<![a-z]){re.escape(st)}(?![a-z])", text):
                    out["country"], out["country_evidence"] = "United States", st
                    break
        m = re.search(r"(?<!born )\b(?:in|during|around|circa|as of|year)\s+((?:19[5-9]|20[0-3])\d)\b", text)
        if m:
            out["year"], out["year_evidence"] = int(m.group(1)), m.group(0).strip()
        return out

    # -- per-family candidates -------------------------------------------------

    def _catalog(self) -> List[str]:
        return self.engine.catalog_keys()

    def _wvs_covers(self, country_key: str) -> Optional[float]:
        """Max coordinate snap error (degrees) if WVS7 can proxy this country."""
        cov = self.coverage.get("wvs/wvs7_pooled", {}).get("coordinate_values")
        if not cov:
            return None
        try:
            _, lon, lat = core.resolve_country_to_coords(country_key)
        except ValueError:
            return None
        lon_s = float(core._nearest_allowed_numeric_value(lon, cov["O1_LONGITUDE"], "O1_LONGITUDE"))
        lat_s = float(core._nearest_allowed_numeric_value(lat, cov["O2_LATITUDE"], "O2_LATITUDE"))
        err = max(abs(lon_s - lon), abs(lat_s - lat))
        return err if err <= 2.0 else None

    @staticmethod
    def _dist(year: Optional[int], lo: int, hi: int) -> float:
        if year is None:
            return 0.0
        if lo <= year <= hi:
            return 0.0
        return float(lo - year if year < lo else year - hi)

    def _country_support(self, key: str) -> Tuple[Dict[str, List[str]], List[str]]:
        """Country-bearing variables of a model (support) and NATION hints."""
        rec = self.coverage.get(key, {})
        possible: Dict[str, List[str]] = {}
        if rec.get("country_feature"):
            possible[rec["country_feature"]] = list(rec.get("country_values") or [])
        if rec.get("iso_feature"):
            possible[rec["iso_feature"]] = list(rec.get("iso_values") or [])
        hints = list((rec.get("nation_features") or {}).keys())
        for v in hints:
            possible[v] = list(rec["nation_features"][v])
        return possible, hints

    def _geo_for(self, key: str, country_key: str, country_raw: str) -> Optional[Tuple[str, str, Optional[str]]]:
        possible, hints = self._country_support(key)
        if not possible:
            return None
        for req in dict.fromkeys([country_raw, country_key]):
            var, val = localized.find_categorical_country_assignment(set(possible), possible, req, hint_features=hints)
            if var is not None:
                return "categorical", f"{var} = {val!r}", val
        partial = sorted({
            str(v) for vals in possible.values() for v in vals
            if _label_key(localized._value_country_name(v) if str(v).strip().upper() in localized.ISO_COUNTRY_NAMES else v)[0] == country_key
        })
        if partial:
            return "coverage_only", f"{country_key.title()} present as {', '.join(partial[:3])}; no unique category, so country is contextual", None
        return None

    def _gss(self, year: Optional[int]) -> Optional[Candidate]:
        waves = sorted(y for y in (self._year_of(k) for k in self._catalog() if k.startswith("gss/")) if y)
        if not waves:
            return None
        if year is None:
            y, mode, note, d = waves[-1], "latest", f"latest GSS wave ({waves[-1]})", 0.0
        elif year in waves:
            y, mode, note, d = year, "exact", f"GSS {year} wave", 0.0
        else:
            y = min(waves, key=lambda w: (abs(w - year), -w))
            mode, note, d = "nearest", f"no GSS wave in {year}; nearest wave is {y}", float(abs(y - year))
        return Candidate(
            model_key=f"gss/gss_{y}", family="gss", label=f"GSS {y}",
            geo_mode="national_survey", geo_note="United States national sample; country is not a model variable",
            time_mode=mode, time_note=note, time_distance=d, recency=y, overrides={"year": y},
        )

    @staticmethod
    def _year_of(key: str) -> Optional[int]:
        m = re.fullmatch(r"gss/gss_(\d{4})", key)
        return int(m.group(1)) if m else None

    def _afro(self, country_key: str, country_raw: str, year: Optional[int]) -> Optional[Candidate]:
        best: Optional[Candidate] = None
        for key in self._catalog():
            if not key.startswith("afrobarometer/"):
                continue
            rnd = key.split("/", 1)[1].lower()
            if rnd not in AFRO_ROUND_YEARS:
                continue
            geo = self._geo_for(key, country_key, country_raw)
            if geo is None:
                continue
            lo, hi = AFRO_ROUND_YEARS[rnd]
            d = self._dist(year, lo, hi)
            mode = "latest" if year is None else ("exact" if d == 0 else "nearest")
            note = f"round {rnd.upper()} fieldwork ≈{lo}–{hi}" + ("" if d == 0 or year is None else f" ({int(d)} years from {year})")
            ov: Dict[str, Any] = {}
            if year is not None:
                ov["year"] = year
            c = Candidate(key, "afrobarometer", f"Afrobarometer {rnd.upper()}", geo[0], geo[1], mode, note, d, hi, ov, geo[2])
            if best is None or c.sort_key() < best.sort_key():
                best = c
        return best

    def _eb(self, country_key: str, country_raw: str, year: Optional[int], when: Optional[date]) -> Optional[Candidate]:
        router = self.engine.eurobarometer
        from dtag_engine import za_of_model
        best: Optional[Candidate] = None
        for key in self._catalog():
            if not key.startswith("eurobarometer/"):
                continue
            geo = self._geo_for(key, country_key, country_raw)
            if geo is None:
                continue
            za = za_of_model(key)
            w = router.wave_for_za(za) if (za and router.available()) else None
            if w is None:
                continue  # no fieldwork dates: not auto-recommended by time
            if when is not None:
                d = 0.0 if w.start_date <= when <= w.end_date else float(min(abs((w.start_date - when).days), abs((w.end_date - when).days))) / 365.25
            else:
                d = self._dist(year, w.start_date.year, w.end_date.year)
            if not w.auto_select:
                d += 50  # cumulative/trend files only as a last resort
            mode = "latest" if (year is None and when is None) else ("exact" if d == 0 else "nearest")
            note = f"{za} fieldwork {w.start_date} … {w.end_date}"
            ov: Dict[str, Any] = {"za": za}
            if when is not None and d == 0:
                ov = {"date": when.isoformat()}
            c = Candidate(key, "eurobarometer", f"Eurobarometer {za}", geo[0], geo[1], mode, note, round(d, 3),
                          w.end_date.toordinal() / 365.25, ov, geo[2])
            if best is None or c.sort_key() < best.sort_key():
                best = c
        if best is not None and year is not None and when is None and best.time_distance == 0:
            n = sum(1 for w in router.waves_in_year(year))
            best.time_note += f" · latest of the {year} waves covering {country_key.title()} ({n} waves that year; pick a date or ZA to change)"
        return best

    def _wvs(self, country_key: str, year: Optional[int]) -> Optional[Candidate]:
        key = "wvs/wvs7_pooled"
        if key not in self._catalog():
            return None
        err = self._wvs_covers(country_key)
        if err is None:
            return None
        years = sorted(int(y) for y in self.coverage.get(key, {}).get("year_values", []) if str(y).isdigit()) or [2017, 2023]
        d = self._dist(year, years[0], years[-1])
        ov: Dict[str, Any] = {}
        if year is not None and year in years:
            ov["year"] = year
            mode, note = "exact", f"A_YEAR={year} hard-conditioned"
        elif year is None:
            mode, note = "latest", f"pooled {years[0]}–{years[-1]}; year not conditioned"
        else:
            mode, note = "nearest", f"WVS7 covers {years[0]}–{years[-1]}; {year} is outside, year not conditioned"
        return Candidate(
            key, "wvs", "WVS7 pooled", "coordinates",
            f"O1_LONGITUDE/O2_LATITUDE snapped to the model's support (≤{err:.1f}° from the country centroid)",
            mode, note, d, years[-1], ov,
        )

    # -- public ---------------------------------------------------------------

    def recommend(
        self,
        persona: str = "",
        country: str = "",
        year: Optional[int] = None,
        when: Optional[str] = None,
        preferred_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        detected = self.detect(persona)
        messages: List[str] = []
        country_in = (country or "").strip()
        sources = {"country": "input" if country_in else None, "year": "input" if year is not None else None}
        if not country_in and detected["country"]:
            country_in = detected["country"]
            sources["country"] = "description"
        if year is None and detected["year"]:
            year = detected["year"]
            sources["year"] = "description"
        when_d: Optional[date] = None
        if when:
            try:
                when_d = date.fromisoformat(when)
            except ValueError:
                messages.append("Date must use YYYY-MM-DD; ignored.")
            else:
                if year is None:
                    year = when_d.year
                    sources["year"] = "date"
        assumed = False
        if not country_in:
            country_in = "United States"
            sources["country"] = "default"
            assumed = True
            messages.append("No country given or detected; assuming the United States (GSS).")
        ckey = norm_country(country_in)

        cands: List[Candidate] = []
        if ckey == "united states":
            c = self._gss(year)
            if c:
                if assumed:
                    c.geo_mode = "assumed"
                cands.append(c)
        for fn in (lambda: self._afro(ckey, country_in, year), lambda: self._eb(ckey, country_in, year, when_d), lambda: self._wvs(ckey, year)):
            c = fn()
            if c:
                cands.append(c)
        cands.sort(key=lambda c: c.sort_key())
        if assumed:
            # Nothing said where the respondent lives: the assumed-US GSS model
            # stays the default; other surveys remain listed as alternatives.
            cands.sort(key=lambda c: c.family != "gss")
        if not cands:
            messages.append(f"No native DTAG model covers {country_in!r}.")
        default = cands[0].model_key if cands else None
        if preferred_model and any(c.model_key == preferred_model for c in cands):
            default = preferred_model

        reason = None
        if cands:
            top = next(c for c in cands if c.model_key == default)
            reason = f"{top.label}: {top.time_note}; {top.geo_note}."
            if len(cands) > 1:
                others = ", ".join(c.label for c in cands if c.model_key != default)
                reason += f" Also available: {others}."

        return {
            "input": {"persona": bool(persona), "country": country, "year": year, "date": when},
            "resolved": {"country": self.country_index().get(ckey, {"name": country_in})["name"], "country_key": ckey,
                         "year": year, "date": when_d.isoformat() if when_d else None, "sources": sources},
            "detected": detected,
            "candidates": [self._cand_dict(c) for c in cands],
            "default": default,
            "choice_required": len({c.family for c in cands}) > 1,
            "reason": reason,
            "messages": messages,
        }

    def _cand_dict(self, c: Candidate) -> Dict[str, Any]:
        rec = self.engine.model_record(c.model_key)
        return {
            "model_key": c.model_key,
            "family": c.family,
            "family_label": FAMILY_LABEL.get(c.family, c.family),
            "label": c.label,
            "geo": {"mode": c.geo_mode, "note": c.geo_note, "value": c.conditioned_value},
            "time": {"mode": c.time_mode, "note": c.time_note, "distance_years": c.time_distance},
            "overrides": dict(c.overrides),
            "installed": rec["installed"],
            "loaded": rec["loaded"],
            "status": rec["status"]["state"],
            "archive_bytes": rec["archive_bytes"],
            "ideology_available": rec["ideology_available"],
        }

    def countries(self) -> List[Dict[str, Any]]:
        return sorted(
            ({"key": k, "name": v["name"], "families": v["families"]} for k, v in self.country_index().items() if v["families"]),
            key=lambda r: r["name"],
        )
