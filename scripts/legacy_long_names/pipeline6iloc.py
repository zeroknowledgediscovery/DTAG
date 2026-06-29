#!/usr/bin/env python3
"""
pipeline6iloc.py (DTAG Pipeline 6, WVS/location-aware)

Merged version of pipeline6.py and pipeline5iloc.py.

Keeps the Pipeline 6 experiment features:
1) Ideology tracking per iteration using polar reference vectors and qdistance.
2) Ideology time-series CSV written to logs.
3) Question-sequence CSV written to logs.
4) Autoplay mode: provide a CSV of questions and the run becomes non-interactive.

Adds the WVS/location-aware conditioning features:
5) Supports forcing A_YEAR via --year.
6) Supports forcing location context via --country and/or --continent.
7) Country/continent is encoded through O1_LONGITUDE and O2_LATITUDE when those
   variables exist in the current model.
8) Country/continent names are validated against internal dictionaries.
9) Target coordinates are snapped to the nearest allowed qnet support values.
10) Metadata/logging includes requested and resolved geography.

Ideology index:
  I(s) = ( d(sL, s) - d(sR, s) ) / d(sL, sR)
where d = qdistance(.,.,model,model), and s is the current full state vector.

Requirements:
  pip install openai pandas numpy quasinet

Env:
  export OPENAI_API_KEY="..."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import OrderedDict

import numpy as np
import pandas as pd
from openai import OpenAI
from quasinet.qnet import load_qnet, qdistance


# -----------------------------
# Filesystem helpers
# -----------------------------

def _ensure_dir(path: str) -> str:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _safe_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if not tag:
        return "run"
    tag = re.sub(r"[^A-Za-z0-9._-]+", "_", tag)
    tag = tag.strip("._-")
    return tag or "run"


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _sha1_hex(s: str, n: int = 12) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def _abspath(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return os.path.abspath(p)


# -----------------------------
# Logging (tee stdout/stderr)
# -----------------------------

class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        for s in self.streams:
            try:
                if hasattr(s, "isatty") and s.isatty():
                    return True
            except Exception:
                pass
        return False

    def fileno(self) -> int:
        for s in self.streams:
            try:
                if hasattr(s, "fileno"):
                    return s.fileno()
            except Exception:
                pass
        raise OSError("Tee has no fileno()")


# -----------------------------
# Pretty printing
# -----------------------------

def _supports_color() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _color(s: str, code: str) -> str:
    if not _supports_color():
        return s
    return f"\033[{code}m{s}\033[0m"


def _term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default


def _section(title: str, body: str, color_code: str):
    width = _term_width()
    line = "-" * width
    print(_color(line, "90"))
    print(_color(f"{title}", f"1;{color_code}"))
    print(_color(line, "90"))
    print(_color(body, color_code))
    print()


@dataclass
class VarItem:
    variable: str
    question_text: str
    response: str


def pretty_print_output(
    model_path: str,
    persona_text: str,
    persona_assignments: Dict[str, str],
    var_set: List[str],
    rationale_vars: str,
    var_items: List[VarItem],
    answer: str,
    ideology: Optional[float] = None,
    timings: Optional[Dict[str, float]] = None,
):
    _section("MODEL", f"{_abspath(model_path)}", "95")
    _section("PERSONA", persona_text.strip(), "96")

    if persona_assignments:
        lines = "\n".join([f"{k} = {v}" for k, v in persona_assignments.items()])
    else:
        lines = "(none)"
    _section("PERSONA ASSIGNMENTS (CURRENT STATE)", lines, "36")

    _section("SELECTED VARIABLES", ",".join(var_set), "94")
    _section("SELECTION RATIONALE", rationale_vars.replace("\n", " ").strip(), "90")

    lines = "\n".join([f"{it.variable} -> {it.response}" for it in var_items])
    _section("RESPONSES (ANCHORS)", lines, "93")

    if ideology is not None:
        _section("IDEOLOGY INDEX", f"{ideology:.6f}", "35")

    _section("RESPONDENT ANSWER", answer.strip(), "92")

    if timings:
        tlines = "\n".join([f"{k}: {v:.3f}s" for k, v in timings.items()])
        _section("TIMING", tlines, "37")


# -----------------------------
# Utilities
# -----------------------------

def normalize_varname(v: str) -> str:
    v = (v or "").strip()
    v = v.replace("-", "_")
    return v


def _norm(s: str) -> str:
    s = str(s or "")
    s = s.replace("\u00a0", " ").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _tokenize(s: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", _norm(s))


def _get_output_text(resp) -> str:
    if hasattr(resp, "output_text") and isinstance(resp.output_text, str) and resp.output_text:
        return resp.output_text
    try:
        parts = []
        for item in resp.output:
            for c in getattr(item, "content", []):
                if getattr(c, "type", None) == "output_text":
                    parts.append(getattr(c, "text", ""))
                elif hasattr(c, "text"):
                    parts.append(c.text)
        return "".join(parts).strip()
    except Exception:
        return ""


def _try_float(x) -> Optional[float]:
    try:
        return float(str(x).strip())
    except Exception:
        return None


def _canonicalize_place_name(s: str) -> str:
    s = _norm(s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# -----------------------------
# Geography dictionaries
# -----------------------------
# Representative coordinates, usually country centroids.
# Good enough for current proxy-conditioning.
# Longitudes, latitudes.

COUNTRY_TO_COORDS_RAW: Dict[str, Tuple[float, float]] = {
    "albania": (20.17, 41.15),
    "andorra": (1.52, 42.51),
    "argentina": (-63.62, -38.42),
    "armenia": (45.04, 40.07),
    "australia": (133.78, -25.27),
    "austria": (14.55, 47.52),
    "azerbaijan": (47.58, 40.14),
    "bangladesh": (90.36, 23.68),
    "belarus": (27.95, 53.71),
    "bolivia": (-63.59, -16.29),
    "bosnia and herzegovina": (17.68, 43.92),
    "bosnia": (17.68, 43.92),
    "brazil": (-51.93, -14.24),
    "bulgaria": (25.49, 42.73),
    "canada": (-106.35, 56.13),
    "chile": (-71.54, -35.68),
    "china": (104.20, 35.86),
    "colombia": (-74.30, 4.57),
    "croatia": (15.20, 45.10),
    "cyprus": (33.43, 35.13),
    "czechia": (15.47, 49.82),
    "czech republic": (15.47, 49.82),
    "denmark": (9.50, 56.26),
    "ecuador": (-78.18, -1.83),
    "egypt": (30.80, 26.82),
    "estonia": (25.01, 58.60),
    "ethiopia": (40.49, 9.15),
    "finland": (25.75, 61.92),
    "france": (2.21, 46.23),
    "georgia": (43.36, 42.32),
    "germany": (10.45, 51.17),
    "great britain": (-2.50, 54.00),
    "united kingdom": (-2.50, 54.00),
    "greece": (21.82, 39.07),
    "guatemala": (-90.23, 15.78),
    "hong kong": (114.17, 22.32),
    "hong kong sar": (114.17, 22.32),
    "hungary": (19.50, 47.16),
    "iceland": (-19.02, 64.96),
    "india": (78.96, 20.59),
    "indonesia": (113.92, -0.79),
    "iran": (53.69, 32.43),
    "iraq": (43.68, 33.22),
    "italy": (12.57, 41.87),
    "japan": (138.25, 36.20),
    "jordan": (36.24, 30.59),
    "kazakhstan": (66.92, 48.02),
    "kenya": (37.91, -0.02),
    "kyrgyzstan": (74.77, 41.20),
    "latvia": (24.60, 56.88),
    "lebanon": (35.86, 33.85),
    "libya": (17.23, 26.34),
    "lithuania": (23.88, 55.17),
    "macao": (113.54, 22.20),
    "macau": (113.54, 22.20),
    "macao sar": (113.54, 22.20),
    "malaysia": (101.98, 4.21),
    "maldives": (73.22, 3.20),
    "mexico": (-102.55, 23.63),
    "mongolia": (103.85, 46.86),
    "montenegro": (19.37, 42.71),
    "morocco": (-7.09, 31.79),
    "myanmar": (95.96, 21.92),
    "netherlands": (5.29, 52.13),
    "new zealand": (174.89, -40.90),
    "nicaragua": (-85.21, 12.87),
    "nigeria": (8.68, 9.08),
    "north macedonia": (21.75, 41.61),
    "northern ireland": (-6.49, 54.79),
    "norway": (8.47, 60.47),
    "pakistan": (69.35, 30.38),
    "peru": (-75.02, -9.19),
    "philippines": (121.77, 12.88),
    "poland": (19.15, 51.92),
    "portugal": (-8.22, 39.40),
    "puerto rico": (-66.59, 18.22),
    "romania": (24.97, 45.94),
    "russia": (105.32, 61.52),
    "russian federation": (105.32, 61.52),
    "serbia": (21.01, 44.02),
    "singapore": (103.82, 1.35),
    "slovakia": (19.70, 48.67),
    "slovenia": (14.99, 46.15),
    "south korea": (127.98, 35.91),
    "korea": (127.98, 35.91),
    "spain": (-3.75, 40.46),
    "sweden": (18.64, 60.13),
    "switzerland": (8.23, 46.82),
    "taiwan": (120.96, 23.70),
    "taiwan roc": (120.96, 23.70),
    "tajikistan": (71.28, 38.86),
    "thailand": (100.99, 15.87),
    "tunisia": (9.54, 33.89),
    "turkey": (35.24, 38.96),
    "ukraine": (31.17, 48.38),
    "united states": (-98.58, 39.83),
    "united states of america": (-98.58, 39.83),
    "uruguay": (-55.77, -32.52),
    "uzbekistan": (64.59, 41.38),
    "venezuela": (-66.59, 6.42),
    "vietnam": (108.28, 14.06),
    "zimbabwe": (29.15, -19.02),
}

COUNTRY_ALIASES: Dict[str, str] = {
    "usa": "united states",
    "us": "united states",
    "u s a": "united states",
    "uk": "united kingdom",
    "u k": "united kingdom",
    "gbr": "great britain",
    "england": "great britain",
    "scotland": "great britain",
    "wales": "great britain",
    "alb": "albania",
    "and": "andorra",
    "arg": "argentina",
    "arm": "armenia",
    "aus": "australia",
    "aut": "austria",
    "aze": "azerbaijan",
    "bgd": "bangladesh",
    "blr": "belarus",
    "bol": "bolivia",
    "bih": "bosnia and herzegovina",
    "bra": "brazil",
    "bgr": "bulgaria",
    "can": "canada",
    "chl": "chile",
    "chn": "china",
    "col": "colombia",
    "hrv": "croatia",
    "cyp": "cyprus",
    "cze": "czechia",
    "dnk": "denmark",
    "ecu": "ecuador",
    "egy": "egypt",
    "est": "estonia",
    "eth": "ethiopia",
    "fin": "finland",
    "fra": "france",
    "geo": "georgia",
    "deu": "germany",
    "ger": "germany",
    "grc": "greece",
    "gtm": "guatemala",
    "hkg": "hong kong",
    "hun": "hungary",
    "isl": "iceland",
    "ind": "india",
    "idn": "indonesia",
    "irn": "iran",
    "irq": "iraq",
    "ita": "italy",
    "jpn": "japan",
    "jor": "jordan",
    "kaz": "kazakhstan",
    "ken": "kenya",
    "kgz": "kyrgyzstan",
    "lva": "latvia",
    "lbn": "lebanon",
    "lby": "libya",
    "ltu": "lithuania",
    "mac": "macao",
    "mys": "malaysia",
    "mdv": "maldives",
    "mex": "mexico",
    "mng": "mongolia",
    "mne": "montenegro",
    "mar": "morocco",
    "mor": "morocco",
    "mmr": "myanmar",
    "nld": "netherlands",
    "nzl": "new zealand",
    "nic": "nicaragua",
    "nga": "nigeria",
    "mkd": "north macedonia",
    "nir": "northern ireland",
    "nor": "norway",
    "pak": "pakistan",
    "per": "peru",
    "phl": "philippines",
    "pol": "poland",
    "prt": "portugal",
    "pri": "puerto rico",
    "rou": "romania",
    "rus": "russia",
    "srb": "serbia",
    "sgp": "singapore",
    "svk": "slovakia",
    "svn": "slovenia",
    "kor": "south korea",
    "esp": "spain",
    "swe": "sweden",
    "che": "switzerland",
    "twn": "taiwan",
    "tjk": "tajikistan",
    "tha": "thailand",
    "tun": "tunisia",
    "tur": "turkey",
    "ukr": "ukraine",
    "ury": "uruguay",
    "uzb": "uzbekistan",
    "ven": "venezuela",
    "vnm": "vietnam",
    "zwe": "zimbabwe",
}

CONTINENT_TO_COORDS_RAW: Dict[str, Tuple[float, float]] = {
    "africa": (20.0, 2.0),
    "asia": (90.0, 34.0),
    "europe": (15.0, 54.0),
    "north america": (-100.0, 45.0),
    "south america": (-60.0, -15.0),
    "oceania": (140.0, -25.0),
    "australia and oceania": (140.0, -25.0),
    "middle east": (45.0, 29.0),
    "mena": (20.0, 27.0),
    "latin america": (-70.0, -15.0),
}

CONTINENT_ALIASES: Dict[str, str] = {
    "na": "north america",
    "n america": "north america",
    "north america": "north america",
    "sa": "south america",
    "s america": "south america",
    "south america": "south america",
    "eu": "europe",
    "europe": "europe",
    "asia": "asia",
    "africa": "africa",
    "oceania": "oceania",
    "australia": "oceania",
    "anz": "oceania",
    "middle east": "middle east",
    "mena": "mena",
    "latin america": "latin america",
    "latam": "latin america",
}


def get_country_coords_dict() -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    for k, v in COUNTRY_TO_COORDS_RAW.items():
        out[_canonicalize_place_name(k)] = v
    for alias, canonical in COUNTRY_ALIASES.items():
        ck = _canonicalize_place_name(canonical)
        if ck in out:
            out[_canonicalize_place_name(alias)] = out[ck]
    return out


def get_continent_coords_dict() -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    for k, v in CONTINENT_TO_COORDS_RAW.items():
        out[_canonicalize_place_name(k)] = v
    for alias, canonical in CONTINENT_ALIASES.items():
        ck = _canonicalize_place_name(canonical)
        if ck in out:
            out[_canonicalize_place_name(alias)] = out[ck]
    return out


COUNTRY_TO_COORDS = get_country_coords_dict()
CONTINENT_TO_COORDS = get_continent_coords_dict()


def list_supported_countries() -> List[str]:
    keep = []
    raw_keys = sorted(COUNTRY_TO_COORDS_RAW.keys())
    for k in raw_keys:
        keep.append(k)
    return keep


def list_supported_continents() -> List[str]:
    return sorted(CONTINENT_TO_COORDS_RAW.keys())


def resolve_country_to_coords(country: str) -> Tuple[str, float, float]:
    key = _canonicalize_place_name(country)
    if key not in COUNTRY_TO_COORDS:
        raise ValueError(
            f"Unknown country '{country}'. Supported countries include: "
            + ", ".join(list_supported_countries())
        )
    lon, lat = COUNTRY_TO_COORDS[key]
    return key, lon, lat


def resolve_continent_to_coords(continent: str) -> Tuple[str, float, float]:
    key = _canonicalize_place_name(continent)
    if key not in CONTINENT_TO_COORDS:
        raise ValueError(
            f"Unknown continent '{continent}'. Supported continents include: "
            + ", ".join(list_supported_continents())
        )
    lon, lat = CONTINENT_TO_COORDS[key]
    return key, lon, lat


def _nearest_allowed_numeric_value(target: float, allowed: List[str], var_name: str) -> str:
    vals: List[Tuple[float, str]] = []
    for a in allowed:
        fa = _try_float(a)
        if fa is None:
            continue
        if var_name in ("O1_LONGITUDE", "O2_LATITUDE") and fa == -999.0:
            continue
        vals.append((abs(fa - target), a))
    if not vals:
        raise ValueError(f"No numeric allowed values available to snap to for {var_name}.")
    vals.sort(key=lambda t: t[0])
    return vals[0][1]



# -----------------------------
# Map loading
# -----------------------------

def load_var_map(map_csv: str) -> Dict[str, str]:
    df = pd.read_csv(map_csv, dtype=str).fillna("")
    if "variable" not in df.columns:
        raise ValueError("map_csv must have a 'variable' column")

    text_col = None
    for c in ("question_text_filled", "question_text", "dta_variable_label", "pdf_short_label"):
        if c in df.columns:
            text_col = c
            break
    if text_col is None:
        raise ValueError("map_csv must contain one of: question_text_filled, question_text, dta_variable_label, pdf_short_label")

    out: Dict[str, str] = {}
    for _, r in df.iterrows():
        v = str(r["variable"]).strip()
        if not v:
            continue
        out[normalize_varname(v)] = str(r[text_col]).strip()
    if not out:
        raise ValueError("No variables loaded from map_csv")
    return out


# -----------------------------
# Candidate prefilter
# -----------------------------

def lexical_prefilter(var_map: Dict[str, str], question: str, top_n: int) -> List[Tuple[str, str]]:
    q_toks = set(_tokenize(question))
    scored = []
    for v, txt in var_map.items():
        t = _norm(txt)
        t_toks = set(_tokenize(t))
        overlap = len(q_toks & t_toks)
        bonus = 0
        for tok in q_toks:
            if len(tok) >= 5 and tok in t:
                bonus += 1
        scored.append((overlap + 0.25 * bonus, v, txt))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top_n = max(1, int(top_n))
    return [(v, txt) for _, v, txt in scored[:top_n]]


def candidates_text(cands: List[Tuple[str, str]], max_q_len: int = 260) -> str:
    lines = []
    for v, q in cands:
        q2 = (q or "").replace("\n", " ").strip()
        if len(q2) > max_q_len:
            q2 = q2[: max_q_len - 3] + "..."
        lines.append(f"{v}\t{q2}")
    return "\n".join(lines)


# -----------------------------
# OpenAI steps
# -----------------------------

def llm_select_variables(
    client: OpenAI,
    question: str,
    candidates_block: str,
    k: int,
    model: str,
) -> Tuple[List[str], str]:
    schema = {
        "type": "object",
        "properties": {
            "variables": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": max(1, int(k))},
            "rationale": {"type": "string"},
        },
        "required": ["variables", "rationale"],
        "additionalProperties": False,
    }

    prompt = (
        "Task: map a user question to survey variables.\n"
        "Choose up to K variables from the candidate list only.\n"
        "Prefer the most semantically direct matches. Include complementary variables if useful.\n"
        "Return JSON only (no markdown).\n\n"
        f"K={k}\n\n"
        f"USER QUESTION:\n{question}\n\n"
        "CANDIDATES (var<TAB>question text):\n"
        f"{candidates_block}\n"
    )

    resp = client.responses.create(
        model=model,
        input=prompt,
        text={"format": {"type": "json_schema", "name": "variable_selection", "schema": schema, "strict": True}},
        temperature=0.2,
    )

    txt = _get_output_text(resp)
    if not txt:
        raise RuntimeError("OpenAI response had no text output to parse.")
    obj = json.loads(txt)

    variables = [normalize_varname(str(v).strip()) for v in obj.get("variables", []) if str(v).strip()]
    variables = list(dict.fromkeys(variables))
    rationale = str(obj.get("rationale", "")).strip()
    return variables, rationale


def llm_persona_to_assignments(
    client: OpenAI,
    persona_text: str,
    allowed: Dict[str, List[str]],
    max_assign: int,
    model: str,
) -> Tuple[Dict[str, str], str]:
    lines = []
    for v, opts in allowed.items():
        show = opts[:12]
        tail = "" if len(opts) <= 12 else " ..."
        lines.append(f"{v}\t{'; '.join(show)}{tail}")
    allowed_block = "\n".join(lines)

    schema = {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"variable": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["variable", "value"],
                    "additionalProperties": False,
                },
                "minItems": 0,
                "maxItems": max(0, int(max_assign)),
            },
            "rationale": {"type": "string"},
        },
        "required": ["assignments", "rationale"],
        "additionalProperties": False,
    }

    prompt = (
        "Task: convert a persona description into a small set of survey-variable assignments.\n"
        "Rules:\n"
        "1) Choose up to MAX_ASSIGN variables from the provided list only.\n"
        "2) For each chosen variable, pick VALUE exactly from its listed allowed responses.\n"
        "3) Prefer variables that clearly follow from the persona (age, education, ideology, media use, religion, etc.).\n"
        "4) If persona is too vague, return fewer assignments.\n"
        "Return JSON only.\n\n"
        f"MAX_ASSIGN={max_assign}\n\n"
        f"PERSONA:\n{persona_text}\n\n"
        "ALLOWED (var<TAB>responses):\n"
        f"{allowed_block}\n"
    )

    resp = client.responses.create(
        model=model,
        input=prompt,
        text={"format": {"type": "json_schema", "name": "persona_assignments", "schema": schema, "strict": True}},
        temperature=0.3,
    )

    txt = _get_output_text(resp)
    if not txt:
        raise RuntimeError("OpenAI response had no text output to parse (persona assignments).")
    obj = json.loads(txt)

    assigns: Dict[str, str] = {}
    for a in obj.get("assignments", []):
        v = normalize_varname(str(a.get("variable", "")).strip())
        val = str(a.get("value", "")).strip()
        if not v or not val:
            continue
        assigns[v] = val
    rationale = str(obj.get("rationale", "")).strip()
    return assigns, rationale


def llm_craft_human_answer(
    client: OpenAI,
    persona_text: str,
    user_question: str,
    var_items: List[VarItem],
    model: str,
) -> str:
    evidence_lines = []
    for it in var_items:
        evidence_lines.append(f"VAR={it.variable}\nQUESTION_TEXT={it.question_text}\nRESPONSE={it.response}\n")

    prompt = (
        "Write a response as if you are a single human survey respondent.\n"
        "You have a persona description. Answer the user's question in first person.\n"
        "Requirements:\n"
        "1) Use first person ('I', 'my').\n"
        "2) Do not mention surveys, variables, models, probabilities, files, or analysis.\n"
        "3) Stay consistent with the persona.\n"
        "4) Use the provided RESPONSE anchors as the factual spine. Do not invent extra factual claims.\n"
        "5) 2-7 sentences.\n\n"
        f"PERSONA:\n{persona_text}\n\n"
        f"USER QUESTION:\n{user_question}\n\n"
        "ANCHORS:\n" + "\n---\n".join(evidence_lines)
    )

    resp = client.responses.create(model=model, input=prompt, temperature=0.7)
    return _get_output_text(resp).strip()


# -----------------------------
# Qnet backend helpers
# -----------------------------

def get_possible_responses_from_model(model) -> Dict[str, List[str]]:
    NULL = np.array([""] * len(model.feature_names)).astype("U100")
    resp = model.predict_distributions(NULL)
    out: Dict[str, List[str]] = {}
    for i, v in enumerate(model.feature_names):
        d = resp[i]
        try:
            out[v] = list(d.keys())
        except Exception:
            out[v] = []
    return out


def _model_sig_for_possible(qnet_path: str) -> str:
    p = Path(qnet_path)
    try:
        st = os.stat(p)
        sig = f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    except Exception:
        sig = f"{_abspath(qnet_path)}"
    return sig


def _possible_cache_path(qnet_path: str, assets_dir: str) -> str:
    assets_dir = _ensure_dir(assets_dir)
    p = Path(qnet_path)
    sig = _model_sig_for_possible(qnet_path)
    h = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    base = p.name
    return str(Path(assets_dir) / f"{base}.possible.{h}.json")


def get_possible_responses_cached(model, qnet_path: str, assets_dir: str) -> Dict[str, List[str]]:
    cache_path = _possible_cache_path(qnet_path, assets_dir)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if isinstance(obj, dict):
                out: Dict[str, List[str]] = {}
                for k, v in obj.items():
                    if isinstance(v, list):
                        out[str(k)] = [str(x) for x in v]
                if out:
                    return out
        except Exception:
            pass

    out = get_possible_responses_from_model(model)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception:
        pass
    return out


def build_NULL_with_assignments(model, assigns: Dict[str, str], idx_map: Dict[str, int]) -> np.ndarray:
    NULL = np.array([""] * len(model.feature_names)).astype("U100")
    for v, val in assigns.items():
        j = idx_map.get(v)
        if j is not None:
            NULL[j] = str(val)
    return NULL


def qnet_conditional_distributions(model, NULL_cond: np.ndarray) -> Dict[str, Dict[str, float]]:
    resp = model.predict_distributions(NULL_cond)
    return {model.feature_names[i]: resp[i] for i in range(len(resp))}


def _normalize_probs(dist: Dict[str, float]) -> Tuple[List[str], np.ndarray]:
    keys = list(dist.keys())
    p = np.array([float(dist[k]) for k in keys], dtype=float)
    p[~np.isfinite(p)] = 0.0
    s = p.sum()
    if s <= 0:
        p = np.ones(len(keys), dtype=float) / max(1, len(keys))
    else:
        p = p / s
    return keys, p


def draw_response(dist: Dict[str, float], rng: np.random.Generator) -> str:
    if not dist:
        return ""
    keys, p = _normalize_probs(dist)
    return keys[int(rng.choice(len(keys), p=p))]


def max_prob_response(dist: Dict[str, float]) -> str:
    if not dist:
        return ""
    return max(dist, key=lambda k: float(dist[k]))


def responses_for_vars_from_distributions(
    dists: Dict[str, Dict[str, float]],
    var_set: List[str],
    mode: str = "max",
    seed: Optional[int] = None,
) -> Tuple[Dict[str, str], List[str]]:
    rng = np.random.default_rng(seed) if mode == "draw" else None
    out: Dict[str, str] = {}
    missing: List[str] = []
    for v in var_set:
        v2 = normalize_varname(v)
        if v2 not in dists:
            missing.append(v)
            continue
        if mode == "draw":
            out[v2] = draw_response(dists[v2], rng)  # type: ignore[arg-type]
        else:
            out[v2] = max_prob_response(dists[v2])
    return out, missing


# -----------------------------
# Polar vectors and ideology index
# -----------------------------

def load_polar_vectors_csv(path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Returns (left_map, right_map): variable -> value for each pole.

    Supports:
      - Wide format: variable,left,right  (or variable,L,R; or index column like 'Unnamed: 0')
      - Long format: variable,pole,value

    Column aliasing:
      variable: variable,var,feature,Unnamed: 0,unnamed: 0,index
      left: left,L,lhs
      right: right,R,rhs
      pole: pole,side
      value: value,val,response
    """
    df = pd.read_csv(path, dtype=str).fillna("")
    cols = {c.lower().strip(): c for c in df.columns}

    def _find(*names) -> Optional[str]:
        for n in names:
            if n in cols:
                return cols[n]
        return None

    var_col = _find("variable", "var", "feature", "unnamed: 0", "unnamed:0", "index")
    if var_col is None:
        if len(df.columns) >= 1:
            var_col = df.columns[0]
        else:
            raise ValueError(f"polar_vectors.csv has no columns: {path}")

    left_col = _find("left", "l", "lhs")
    right_col = _find("right", "r", "rhs")

    pole_col = _find("pole", "side")
    value_col = _find("value", "val", "response")

    left_map: Dict[str, str] = {}
    right_map: Dict[str, str] = {}

    if left_col and right_col:
        for _, r in df.iterrows():
            v = normalize_varname(str(r[var_col]).strip())
            if not v:
                continue
            lv = str(r[left_col]).strip()
            rv = str(r[right_col]).strip()
            if lv:
                left_map[v] = lv
            if rv:
                right_map[v] = rv
        return left_map, right_map

    if pole_col and value_col:
        for _, r in df.iterrows():
            v = normalize_varname(str(r[var_col]).strip())
            if not v:
                continue
            pole = str(r[pole_col]).strip().lower()
            val = str(r[value_col]).strip()
            if not val:
                continue
            if pole in {"left", "l", "lhs"}:
                left_map[v] = val
            elif pole in {"right", "r", "rhs"}:
                right_map[v] = val
        return left_map, right_map

    raise ValueError(
        f"polar_vectors.csv format not recognized at {path}. "
        f"Detected columns: {list(df.columns)}. "
        f"Need either wide (variable + L + R) or long (variable + pole + value)."
    )


def build_full_vector_from_state(model, state: Dict[str, str], idx_map: Dict[str, int]) -> np.ndarray:
    x = np.array([""] * len(model.feature_names)).astype("U100")
    for v, val in state.items():
        j = idx_map.get(v)
        if j is not None:
            x[j] = str(val)
    return x


def build_pole_vector(model, pole_map: Dict[str, str], idx_map: Dict[str, int]) -> np.ndarray:
    x = np.array([""] * len(model.feature_names)).astype("U100")
    for v, val in pole_map.items():
        j = idx_map.get(v)
        if j is not None:
            x[j] = str(val)
    return x


def ideology_index_from_vectors(s: np.ndarray, sL: np.ndarray, sR: np.ndarray, model, dLR: float) -> float:
    if not np.isfinite(dLR) or dLR <= 0:
        return 0.0
    dL = qdistance(sL, s, model, model)
    dR = qdistance(sR, s, model, model)
    if not np.isfinite(dL) or not np.isfinite(dR):
        return 0.0
    return float((dL - dR) / dLR)


# -----------------------------
# Autoplay questions
# -----------------------------

def load_questions_csv(path: str) -> List[str]:
    """
    Reads a CSV of questions and returns a list of non-empty questions.

    Accepted formats:
      - A column named 'question' (preferred)
      - Otherwise: uses the first column as the question text
    """
    df = pd.read_csv(path, dtype=str).fillna("")
    if df.shape[1] == 0:
        return []
    col = "question" if "question" in df.columns else df.columns[0]
    qs = []
    for x in df[col].tolist():
        q = str(x).strip()
        if q:
            qs.append(q)
    return qs


# -----------------------------
# Run ID / report naming
# -----------------------------

def make_run_id(qnet: str, map_csv: str, persona: str, tag: str) -> str:
    s = f"qnet={_abspath(qnet)}|map={_abspath(map_csv)}|persona={persona.strip()}|tag={_safe_tag(tag)}"
    return _sha1_hex(s, 12)


def make_report_base(tag: str, run_id: str) -> str:
    return f"dtag6iloc_{_safe_tag(tag)}_{_timestamp()}_{run_id}"


# -----------------------------
# Geography forcing
# -----------------------------

def build_forced_assignments(
    feat: set,
    possible: Dict[str, List[str]],
    year: Optional[int],
    country: str,
    continent: str,
) -> Tuple["OrderedDict[str, str]", Dict[str, object]]:
    forced: "OrderedDict[str, str]" = OrderedDict()
    geo_meta: Dict[str, object] = {
        "requested_year": year,
        "requested_country": country or None,
        "requested_continent": continent or None,
        "resolved_country_key": None,
        "resolved_continent_key": None,
        "target_longitude": None,
        "target_latitude": None,
        "snapped_O1_LONGITUDE": None,
        "snapped_O2_LATITUDE": None,
    }

    if year is not None:
        if "A_YEAR" not in feat:
            geo_meta["year_warning"] = "A_YEAR not in model features; requested year was recorded in metadata/persona text but not hard-conditioned."
        else:
            year_val = str(year).strip()
            year_opts = set(str(x) for x in possible.get("A_YEAR", []))
            if year_val not in year_opts:
                geo_meta["year_warning"] = f"Requested year {year_val} not allowed for A_YEAR; allowed values include {sorted(year_opts)[:20]}; year not hard-conditioned."
            else:
                forced["A_YEAR"] = year_val

    target_lon = None
    target_lat = None

    if continent:
        ck, clon, clat = resolve_continent_to_coords(continent)
        geo_meta["resolved_continent_key"] = ck
        target_lon = clon
        target_lat = clat

    if country:
        ck, clon, clat = resolve_country_to_coords(country)
        geo_meta["resolved_country_key"] = ck
        target_lon = clon
        target_lat = clat

    if target_lon is not None or target_lat is not None:
        if "O1_LONGITUDE" not in feat or "O2_LATITUDE" not in feat:
            geo_meta["geography_warning"] = "O1_LONGITUDE/O2_LATITUDE not both in model features; requested geography was recorded in metadata/persona text but not hard-conditioned."
        else:
            lon_allowed = possible.get("O1_LONGITUDE", [])
            lat_allowed = possible.get("O2_LATITUDE", [])
            if not lon_allowed or not lat_allowed:
                geo_meta["geography_warning"] = "No possible-response support available for O1_LONGITUDE/O2_LATITUDE; geography not hard-conditioned."
            else:
                lon_val = _nearest_allowed_numeric_value(float(target_lon), lon_allowed, "O1_LONGITUDE")
                lat_val = _nearest_allowed_numeric_value(float(target_lat), lat_allowed, "O2_LATITUDE")

                forced["O1_LONGITUDE"] = lon_val
                forced["O2_LATITUDE"] = lat_val

                geo_meta["target_longitude"] = float(target_lon)
                geo_meta["target_latitude"] = float(target_lat)
                geo_meta["snapped_O1_LONGITUDE"] = lon_val
                geo_meta["snapped_O2_LATITUDE"] = lat_val

    return forced, geo_meta



# -----------------------------
# Main
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="CSV mapping file (variable -> question text)")
    ap.add_argument("--qnet", required=True, help="Qnet model path (e.g., gss_2024.gz)")
    ap.add_argument("--persona", required=True, help="Free-text description of an individual")

    ap.add_argument("--question", default="", help="User plain text question (ignored if --loop or --autoplay_csv)")
    ap.add_argument("--loop", action="store_true", help="Read one question per line from stdin")
    ap.add_argument("--autoplay_csv", default="", help="CSV of questions to run non-interactively in order")
    ap.add_argument("--timing", action="store_true", help="Print timing breakdown per query")

    ap.add_argument("--state_keep", type=int, default=50,
                    help="Max cumulative assignments to keep (most recent kept; prevents huge conditioning)")

    ap.add_argument("--k", type=int, default=6, help="How many variables to select for answering question")
    ap.add_argument("--prefilter", type=int, default=160, help="Candidates shown to LLM after lexical prefilter")
    ap.add_argument("--openai_model", default="gpt-4.1-mini", help="OpenAI model for all LLM steps")

    ap.add_argument("--max_assign", type=int, default=8, help="Max persona-conditioning assignments")
    ap.add_argument("--assign_prefilter", type=int, default=140, help="How many variables to offer for persona assignment")

    ap.add_argument("--resp_mode", choices=["max", "draw"], default="max", help="Response mode per selected var")
    ap.add_argument("--seed", type=int, default=1, help="RNG seed used when resp_mode=draw")

    ap.add_argument("--assets_dir", default="./assets", help="Directory for cached assets (possible responses JSON)")
    ap.add_argument("--logs_dir", default="./logs", help="Directory for run logs and reports")
    ap.add_argument("--tag", default="run", help="Tag string to include in report/log filenames")

    ap.add_argument("--polar_vectors", default=os.path.join("./assets", "polar_vectors.csv"),
                    help="CSV with left/right polar reference vectors")

    # WVS/location-aware forcing
    ap.add_argument("--year", type=int, default=None,
                    help="Force A_YEAR in initial state when A_YEAR exists in the model")
    ap.add_argument("--country", type=str, default="",
                    help="Force country context via representative O1_LONGITUDE/O2_LATITUDE")
    ap.add_argument("--continent", type=str, default="",
                    help="Optional broader geographic prior via representative O1_LONGITUDE/O2_LATITUDE")
    ap.add_argument("--list_countries", action="store_true",
                    help="Print supported countries and exit")
    ap.add_argument("--list_continents", action="store_true",
                    help="Print supported continents and exit")

    args = ap.parse_args()

    if args.list_countries:
        print("\n".join(list_supported_countries()))
        return
    if args.list_continents:
        print("\n".join(list_supported_continents()))
        return

    # Mode selection precedence:
    # autoplay_csv > loop > single question
    mode_autoplay = bool(args.autoplay_csv.strip())
    mode_loop = bool(args.loop) and not mode_autoplay
    mode_single = (not mode_autoplay) and (not mode_loop)

    if mode_single and not args.question.strip():
        print("ERROR: Provide --question, or use --loop, or provide --autoplay_csv.", file=sys.stderr)
        sys.exit(2)

    if mode_autoplay and not os.path.exists(args.autoplay_csv):
        print(f"ERROR: --autoplay_csv not found: {args.autoplay_csv}", file=sys.stderr)
        sys.exit(2)

    assets_dir = _ensure_dir(args.assets_dir)
    logs_dir = _ensure_dir(args.logs_dir)
    tag = _safe_tag(args.tag)

    persona_for_run_id = args.persona
    if args.year is not None:
        persona_for_run_id += f"\n[forced_year={args.year}]"
    if args.country:
        persona_for_run_id += f"\n[forced_country={args.country}]"
    if args.continent:
        persona_for_run_id += f"\n[forced_continent={args.continent}]"

    run_id = make_run_id(args.qnet, args.map, persona_for_run_id, tag)
    report_base = make_report_base(tag, run_id)

    log_path = str(Path(logs_dir) / f"{report_base}.log")
    meta_path = str(Path(logs_dir) / f"{report_base}.meta.json")
    final_state_path = str(Path(logs_dir) / f"{report_base}.final_state.json")

    ideology_csv_path = str(Path(logs_dir) / f"{report_base}.ideology.csv")
    questions_csv_path = str(Path(logs_dir) / f"{report_base}.questions.csv")

    log_fh = open(log_path, "w", encoding="utf-8")
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    sys.stdout = Tee(orig_stdout, log_fh)  # type: ignore[assignment]
    sys.stderr = Tee(orig_stderr, log_fh)  # type: ignore[assignment]

    try:
        timings_init: Dict[str, float] = {}
        t0 = time.time()

        meta: Dict[str, object] = {
            "run_id": run_id,
            "tag": tag,
            "timestamp_local": _timestamp(),
            "paths": {
                "qnet": _abspath(args.qnet),
                "map": _abspath(args.map),
                "assets_dir": _abspath(assets_dir),
                "logs_dir": _abspath(logs_dir),
                "log_path": _abspath(log_path),
                "meta_path": _abspath(meta_path),
                "final_state_path": _abspath(final_state_path),
                "polar_vectors": _abspath(args.polar_vectors),
                "ideology_csv_path": _abspath(ideology_csv_path),
                "questions_csv_path": _abspath(questions_csv_path),
                "autoplay_csv": _abspath(args.autoplay_csv) if mode_autoplay else "",
            },
            "params": {
                "k": args.k,
                "prefilter": args.prefilter,
                "openai_model": args.openai_model,
                "max_assign": args.max_assign,
                "assign_prefilter": args.assign_prefilter,
                "resp_mode": args.resp_mode,
                "seed": args.seed,
                "state_keep": args.state_keep,
                "timing": bool(args.timing),
                "loop": bool(mode_loop),
                "autoplay": bool(mode_autoplay),
                "year": args.year,
                "country": args.country,
                "continent": args.continent,
            },
            "persona": args.persona,
        }

        # Load model once
        model = load_qnet(args.qnet)
        timings_init["load_qnet"] = time.time() - t0
        feat = set(model.feature_names)
        idx_map = {model.feature_names[i]: i for i in range(len(model.feature_names))}

        # Load map and restrict to model features
        t1 = time.time()
        var_map = load_var_map(args.map)
        var_map = {v: q for v, q in var_map.items() if v in feat}
        timings_init["load_map"] = time.time() - t1
        if not var_map:
            print("ERROR: After intersecting map with qnet feature_names, no variables remain.", file=sys.stderr)
            sys.exit(2)

        # Load polar vectors once, build pole vectors once, compute dLR once
        tpol = time.time()
        left_map, right_map = load_polar_vectors_csv(args.polar_vectors)
        left_map = {v: val for v, val in left_map.items() if v in feat}
        right_map = {v: val for v, val in right_map.items() if v in feat}
        sL = build_pole_vector(model, left_map, idx_map)
        sR = build_pole_vector(model, right_map, idx_map)
        dLR = qdistance(sL, sR, model, model)
        timings_init["load_polar_vectors"] = time.time() - tpol
        meta["polar_vectors_summary"] = {
            "n_left_assignments": len(left_map),
            "n_right_assignments": len(right_map),
            "dLR": float(dLR) if np.isfinite(dLR) else None,
        }

        # Possible responses (cached)
        t2 = time.time()
        possible = get_possible_responses_cached(model, args.qnet, assets_dir=assets_dir)
        timings_init["possible_cache"] = time.time() - t2
        meta["paths"]["possible_cache_path"] = _abspath(_possible_cache_path(args.qnet, assets_dir=assets_dir))
        meta["timings_init"] = dict(timings_init)

        persona = args.persona
        if args.continent:
            persona = f"{persona}\nRegion context: {args.continent}"
        if args.country:
            persona = f"{persona}\nCountry context: {args.country}"
        if args.year is not None:
            persona = f"{persona}\nSurvey year: {args.year}"

        # Prep allowed vars for persona assignment (one-time)
        t3 = time.time()
        p_toks = set(_tokenize(persona))
        scored_vars = []
        for v in feat:
            opts = possible.get(v, [])
            if not opts:
                continue
            proxy = var_map.get(v, v)
            t = _norm(proxy)
            t_toks = set(_tokenize(t))
            overlap = len(p_toks & t_toks)
            scored_vars.append((overlap, v))
        scored_vars.sort(key=lambda x: (x[0], x[1]), reverse=True)
        offer_vars = [v for _, v in scored_vars[: max(1, args.assign_prefilter)]]
        allowed_for_llm = {v: possible.get(v, []) for v in offer_vars if possible.get(v, [])}
        timings_init["prep_persona_allowed"] = time.time() - t3

        # Initial persona assignment (one-time)
        t4 = time.time()
        client_assign = OpenAI()
        persona_assigns, persona_rationale = llm_persona_to_assignments(
            client=client_assign,
            persona_text=persona,
            allowed=allowed_for_llm,
            max_assign=args.max_assign,
            model=args.openai_model,
        )
        timings_init["llm_persona_init"] = time.time() - t4

        # Forced year/geography assignments, if requested. These override LLM persona assignments.
        t5 = time.time()
        forced_assigns, geo_meta = build_forced_assignments(
            feat=feat,
            possible=possible,
            year=args.year,
            country=args.country,
            continent=args.continent,
        )
        timings_init["forced_assignments"] = time.time() - t5

        # Validate persona assignments
        state: "OrderedDict[str, str]" = OrderedDict()
        dropped: List[str] = []
        for v, val in persona_assigns.items():
            if v not in feat:
                dropped.append(f"{v} (not in model)")
                continue
            opts = possible.get(v, [])
            if val not in opts:
                dropped.append(f"{v}={val} (not allowed)")
                continue
            state[v] = val

        for v, val in forced_assigns.items():
            state[v] = val

        if dropped:
            print(f"WARNING: Dropped initial persona assignments: {dropped[:20]}", file=sys.stderr)

        meta["persona_assignment_rationale"] = persona_rationale
        meta["persona_assignments_llm_raw"] = dict(persona_assigns)
        meta["persona_assignments_initial"] = dict(state)
        meta["persona_assignments_dropped"] = dropped
        meta["forced_assignments"] = dict(forced_assigns)
        meta["geography"] = geo_meta
        meta["timings_init"] = dict(timings_init)

        # Initial ideology (step 0)
        tI0 = time.time()
        s0 = build_full_vector_from_state(model, dict(state), idx_map)
        ideology0 = ideology_index_from_vectors(s0, sL, sR, model, dLR=dLR)
        timings_init["ideology_init"] = time.time() - tI0
        meta["ideology_initial"] = ideology0

        ideology_series: List[Tuple[int, float]] = [(0, ideology0)]

        # Question sequence record: list of (step, question, source)
        # step 0 reserved for persona init (no question)
        question_series: List[Tuple[int, str, str]] = []

        if args.timing:
            print("TIMING (init)")
            print("-" * 72)
            for k, v in timings_init.items():
                print(f"{k}: {v:.3f}s")
            print()

        records: List[Dict[str, object]] = []

        def _evict_to_limit():
            while len(state) > max(1, int(args.state_keep)):
                state.popitem(last=False)

        def _run_one(question: str, query_idx: int, source: str) -> None:
            timings_q: Dict[str, float] = {}
            tq0 = time.time()

            # Save question to series
            question_series.append((query_idx, question, source))

            # Prefilter candidates for variable selection
            t = time.time()
            cands = lexical_prefilter(var_map, question, top_n=args.prefilter)
            cand_block = candidates_text(cands)
            timings_q["prefilters"] = time.time() - t

            # LLM selects variables
            t = time.time()
            client_vars = OpenAI()
            var_set, rationale_vars = llm_select_variables(
                client=client_vars,
                question=question,
                candidates_block=cand_block,
                k=args.k,
                model=args.openai_model,
            )
            timings_q["llm_select"] = time.time() - t

            # Condition Qnet on current cumulative state
            t = time.time()
            NULL_cond = build_NULL_with_assignments(model, dict(state), idx_map)
            dists_cond = qnet_conditional_distributions(model, NULL_cond)
            timings_q["qnet_predict"] = time.time() - t

            # Keep only valid selected vars
            var_set = [v for v in var_set if v in var_map and v in dists_cond]
            if not var_set:
                print("ERROR: No selected variables remained after intersecting with map ∩ model.", file=sys.stderr)
                return

            # Draw / choose responses
            t = time.time()
            respmap, missing = responses_for_vars_from_distributions(
                dists=dists_cond,
                var_set=var_set,
                mode=args.resp_mode,
                seed=args.seed + query_idx,
            )
            timings_q["draw"] = time.time() - t
            if missing:
                var_set = [v for v in var_set if v in respmap]

            # Update cumulative state with drawn values
            t = time.time()
            updates = {}
            for v in var_set:
                if v in respmap and respmap[v] in possible.get(v, []):
                    if v in state:
                        state.move_to_end(v)
                    state[v] = respmap[v]
                    updates[v] = respmap[v]
            _evict_to_limit()
            timings_q["state_update"] = time.time() - t

            # Ideology index after update
            t = time.time()
            s_vec = build_full_vector_from_state(model, dict(state), idx_map)
            ideol = ideology_index_from_vectors(s_vec, sL, sR, model, dLR=dLR)
            ideology_series.append((query_idx, ideol))
            timings_q["ideology"] = time.time() - t

            var_items = [
                VarItem(variable=v, question_text=var_map.get(v, ""), response=respmap.get(v, ""))
                for v in var_set
            ]

            # Human answer
            t = time.time()
            client_final = OpenAI()
            answer = llm_craft_human_answer(
                client=client_final,
                persona_text=persona,
                user_question=question,
                var_items=var_items,
                model=args.openai_model,
            )
            timings_q["llm_final"] = time.time() - t

            timings_q["total"] = time.time() - tq0

            pretty_print_output(
                model_path=args.qnet,
                persona_text=persona,
                persona_assignments=dict(state),
                var_set=var_set,
                rationale_vars=rationale_vars,
                var_items=var_items,
                answer=answer,
                ideology=ideol,
                timings=timings_q if args.timing else None,
            )

            records.append({
                "query_idx": query_idx,
                "question": question,
                "question_source": source,
                "selected_variables": list(var_set),
                "selection_rationale": rationale_vars,
                "responses": {it.variable: it.response for it in var_items},
                "state_updates": updates,
                "ideology_index": ideol,
                "answer": answer,
                "timings": dict(timings_q) if args.timing else None,
            })

        # Execute questions based on mode
        if mode_autoplay:
            qs = load_questions_csv(args.autoplay_csv)
            if not qs:
                print(f"ERROR: No questions found in autoplay CSV: {args.autoplay_csv}", file=sys.stderr)
                sys.exit(2)
            for i, q in enumerate(qs, start=1):
                _run_one(q, i, source=f"autoplay:{_abspath(args.autoplay_csv)}")

        elif mode_loop:
            idx = 0
            for line in sys.stdin:
                q = line.strip()
                if not q:
                    continue
                if q.lower() in {"exit", "quit"}:
                    break
                idx += 1
                _run_one(q, idx, source="stdin")

        else:
            _run_one(args.question.strip(), 1, source="single")

        # Write final state JSON
        final_state = dict(state)
        with open(final_state_path, "w", encoding="utf-8") as f:
            json.dump(final_state, f, indent=2, ensure_ascii=False)

        # Write ideology time series CSV
        try:
            with open(ideology_csv_path, "w", encoding="utf-8") as f:
                f.write("step,ideology_index\n")
                for step, val in ideology_series:
                    f.write(f"{step},{val}\n")
        except Exception as e:
            print(f"WARNING: Failed to write ideology CSV: {e}", file=sys.stderr)

        # Write questions time series CSV
        try:
            with open(questions_csv_path, "w", encoding="utf-8") as f:
                f.write("step,question,source\n")
                for step, q, src in question_series:
                    q_esc = q.replace('"', '""')
                    src_esc = src.replace('"', '""')
                    f.write(f'{step},"{q_esc}","{src_esc}"\n')
        except Exception as e:
            print(f"WARNING: Failed to write questions CSV: {e}", file=sys.stderr)

        meta["ideology_series_length"] = len(ideology_series)
        meta["questions_series_length"] = len(question_series)

        # Write metadata JSON
        meta["records"] = records
        meta["final_state_size"] = len(final_state)
        meta["timings_init"] = dict(timings_init)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Print outputs
        print("RUN OUTPUTS")
        print("-" * 72)
        print(f"log_file: {log_path}")
        print(f"meta_json: {meta_path}")
        print(f"final_state_json: {final_state_path}")
        print(f"assets_possible_cache: {meta['paths']['possible_cache_path']}")
        print(f"polar_vectors: {_abspath(args.polar_vectors)}")
        print(f"ideology_csv: {ideology_csv_path}")
        print(f"questions_csv: {questions_csv_path}")
        if mode_autoplay:
            print(f"autoplay_source: {_abspath(args.autoplay_csv)}")
        print()

    finally:
        try:
            sys.stdout = orig_stdout  # type: ignore[assignment]
            sys.stderr = orig_stderr  # type: ignore[assignment]
        except Exception:
            pass
        try:
            log_fh.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
