#!/usr/bin/env python3
"""
DTAG core library for the native LSM runtime.

Shared, importable building blocks used by the web app (dtag_engine / dtag_session,
pipeline_localized for geography), the optimizer and the model/asset scripts:

* filesystem/run helpers and terminal formatting;
* semantic maps, lexical and embedding prefilters;
* LLM steps (variable selection, semantic bridges, persona assignment, answer wording);
* native model rows, conditional distributions and response draws;
* geography (country/continent coordinates) and forced assignments;
* ideology poles and the index I(s) = (d(sL, s) - d(sR, s)) / d(sL, sR).

This is the library half of the former single-file pipeline.py; its command-line entry point has
been retired (it remains in Git history).

Requirements:
  pip install openai pandas numpy

Env:
  export OPENAI_API_KEY="..."
"""

from __future__ import annotations

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


# Tokens that should not, by themselves, drive a survey-variable match.
# This prevents generic prompts like "what do you think?" from being forced
# onto arbitrary survey variables.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "could", "did", "do", "does", "doing", "for", "from", "give", "go",
    "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "me", "my", "of", "on",
    "or", "our", "ours", "please", "say", "she", "should", "so", "tell", "than",
    "that", "the", "their", "them", "then", "there", "these", "they", "think",
    "this", "those", "to", "us", "was", "we", "were", "what", "when", "where",
    "whether", "which", "who", "why", "will", "with", "would", "you", "your", "yours",
}


def _content_tokens(s: str) -> set:
    return {tok for tok in _tokenize(s) if tok not in STOPWORDS and len(tok) >= 2}


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

def lexical_prefilter(
    var_map: Dict[str, str],
    question: str,
    top_n: int,
    min_score: float = 1.0,
) -> List[Tuple[str, str]]:
    """Return candidate survey variables with an explicit no-match gate.

    Previous behavior always returned the top N variables, even when the question
    was unrelated to the survey map. That forced downstream LLM selection to pick
    something. This version removes generic prompt words, applies a minimum score,
    and can return an empty candidate list.
    """
    q_toks = _content_tokens(question)
    if not q_toks:
        return []

    scored = []
    for v, txt in var_map.items():
        t = _norm(txt)
        t_toks = _content_tokens(t)
        overlap = len(q_toks & t_toks)
        bonus = 0
        for tok in q_toks:
            if len(tok) >= 5 and tok in t:
                bonus += 1
        score = overlap + 0.25 * bonus
        if score >= float(min_score):
            scored.append((score, v, txt))

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


def semantic_candidates_text(cands: List[Tuple[str, str, float]], max_q_len: int = 260) -> str:
    lines = []
    for v, q, score in cands:
        q2 = (q or "").replace("\n", " ").strip()
        if len(q2) > max_q_len:
            q2 = q2[: max_q_len - 3] + "..."
        lines.append(f"{v}\t{score:.4f}\t{q2}")
    return "\n".join(lines)


def _embedding_cache_path(map_csv: str, assets_dir: str, embedding_model: str) -> str:
    assets_dir = _ensure_dir(assets_dir)
    p = Path(map_csv)
    try:
        st = os.stat(p)
        sig = f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}|{embedding_model}"
    except Exception:
        sig = f"{_abspath(map_csv)}|{embedding_model}"
    h = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    model_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", embedding_model)
    return str(Path(assets_dir) / f"{p.name}.semantic_embeddings.{model_tag}.{h}.json")


def _l2_normalize_vector(x: List[float]) -> List[float]:
    arr = np.array(x, dtype=float)
    n = float(np.linalg.norm(arr))
    if not np.isfinite(n) or n <= 0:
        return [0.0 for _ in x]
    return (arr / n).astype(float).tolist()


def get_var_embeddings_cached(
    client: OpenAI,
    var_map: Dict[str, str],
    map_csv: str,
    assets_dir: str,
    embedding_model: str,
    batch_size: int = 128,
) -> Dict[str, List[float]]:
    """Return normalized text embeddings for survey-variable question text.

    This is used only for the semantic fallback path. The cache is keyed by
    mapping-file path/size/mtime and embedding model, so it is regenerated when
    the map changes.
    """
    cache_path = _embedding_cache_path(map_csv, assets_dir, embedding_model)
    vars_in_order = list(var_map.keys())

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            emb = obj.get("embeddings", {}) if isinstance(obj, dict) else {}
            if isinstance(emb, dict) and all(v in emb for v in vars_in_order):
                return {str(k): [float(x) for x in emb[k]] for k in vars_in_order}
        except Exception:
            pass

    embeddings: Dict[str, List[float]] = {}
    for i in range(0, len(vars_in_order), max(1, int(batch_size))):
        batch_vars = vars_in_order[i:i + max(1, int(batch_size))]
        batch_texts = [f"{v}: {var_map[v]}" for v in batch_vars]
        resp = client.embeddings.create(model=embedding_model, input=batch_texts)
        for v, item in zip(batch_vars, resp.data):
            embeddings[v] = _l2_normalize_vector(list(item.embedding))

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "embedding_model": embedding_model,
                "map_csv": _abspath(map_csv),
                "created_local": _timestamp(),
                "n_variables": len(embeddings),
                "embeddings": embeddings,
            }, f)
    except Exception:
        pass

    return embeddings


def semantic_prefilter(
    client: OpenAI,
    var_map: Dict[str, str],
    question: str,
    top_n: int,
    map_csv: str,
    assets_dir: str,
    embedding_model: str,
    var_embeddings: Optional[Dict[str, List[float]]] = None,
) -> List[Tuple[str, str, float]]:
    """Embedding-based broad semantic retrieval for indirect fallback answers.

    ``var_embeddings`` may be supplied by a caller that already holds the map
    embeddings in memory (for example a persistent DTAG session); otherwise
    they are read from, or written to, the on-disk cache.
    """
    if var_embeddings is None:
        var_embeddings = get_var_embeddings_cached(
            client=client,
            var_map=var_map,
            map_csv=map_csv,
            assets_dir=assets_dir,
            embedding_model=embedding_model,
        )
    q_resp = client.embeddings.create(model=embedding_model, input=[question])
    q_vec = np.array(_l2_normalize_vector(list(q_resp.data[0].embedding)), dtype=float)

    scored: List[Tuple[float, str, str]] = []
    for v, emb in var_embeddings.items():
        e = np.array(emb, dtype=float)
        if e.shape != q_vec.shape:
            continue
        score = float(np.dot(q_vec, e))
        if np.isfinite(score):
            scored.append((score, v, var_map.get(v, "")))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(v, txt, score) for score, v, txt in scored[:max(1, int(top_n))]]


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
            "variables": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": max(1, int(k))},
            "rationale": {"type": "string"},
        },
        "required": ["variables", "rationale"],
        "additionalProperties": False,
    }

    prompt = (
        "Task: map a user question to survey variables.\n"
        "Choose up to K variables from the candidate list only.\n"
        "If none of the candidates are semantically relevant, return an empty variables array.\n"
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


def llm_select_semantic_bridge_variables(
    client: OpenAI,
    question: str,
    candidates_block: str,
    k: int,
    model: str,
    min_confidence: float,
) -> Tuple[List[str], str, List[Dict[str, object]], bool]:
    schema = {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "variables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "variable": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "relation_type": {
                            "type": "string",
                            "enum": ["related_construct", "background_attitude", "value_orientation", "weak"],
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["variable", "confidence", "relation_type", "rationale"],
                    "additionalProperties": False,
                },
                "minItems": 0,
                "maxItems": max(1, int(k)),
            },
            "rationale": {"type": "string"},
        },
        "required": ["answerable", "variables", "rationale"],
        "additionalProperties": False,
    }

    prompt = (
        "Task: find indirect survey anchors for a user question that did not have a direct survey-variable match.\n"
        "The candidate list was retrieved by semantic similarity, not lexical matching.\n"
        "Choose variables only if they give a defensible broad semantic bridge to the user's question.\n"
        "Examples of valid bridges: a climate question can connect to environment/protection/spending items; "
        "a question about immigration may connect to national identity, out-groups, crime, or welfare attitudes.\n"
        "Do not force a bridge. If the candidates do not support a meaningful inferred answer, set answerable=false and return no variables.\n"
        "The embedding_similarity column is only a retrieval score; do not compare it directly with MIN_CONFIDENCE. "
        "Assign confidence as your judgment of whether the candidate is a defensible bridge. "
        "Use confidence >= MIN_CONFIDENCE for ordinary accepted bridges. Return JSON only.\n\n"
        f"K={k}\n"
        f"MIN_CONFIDENCE={min_confidence:.3f}\n\n"
        f"USER QUESTION:\n{question}\n\n"
        "CANDIDATES (var<TAB>embedding_similarity<TAB>question text):\n"
        f"{candidates_block}\n"
    )

    resp = client.responses.create(
        model=model,
        input=prompt,
        text={"format": {"type": "json_schema", "name": "semantic_bridge_selection", "schema": schema, "strict": True}},
        temperature=0.2,
    )

    txt = _get_output_text(resp)
    if not txt:
        raise RuntimeError("OpenAI response had no text output to parse (semantic bridge selection).")
    obj = json.loads(txt)

    bridge_items: List[Dict[str, object]] = []
    variables: List[str] = []
    answerable = bool(obj.get("answerable", False))
    for item in obj.get("variables", []):
        v = normalize_varname(str(item.get("variable", "")).strip())
        try:
            conf = float(item.get("confidence", 0.0))
        except Exception:
            conf = 0.0
        if not v:
            continue
        accepted = conf >= float(min_confidence)
        rec = {
            "variable": v,
            "confidence": conf,
            "relation_type": str(item.get("relation_type", "")).strip(),
            "rationale": str(item.get("rationale", "")).strip(),
            "accepted": bool(accepted),
            "below_confidence_threshold": bool(not accepted),
        }
        bridge_items.append(rec)
        if accepted:
            variables.append(v)

    variables = list(dict.fromkeys(variables))
    rationale = str(obj.get("rationale", "")).strip()
    return variables, rationale, bridge_items, answerable


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


def llm_craft_survey_question(
    client: OpenAI,
    item_text: str,
    responses: List[str],
    model: str,
    *,
    source_incomplete: bool = False,
) -> str:
    """Phrase one survey item as a single natural, neutral question for a respondent.

    The wording must keep the item's meaning so the question maps onto that item, must be
    answerable with the item's response options, and must not suggest or favour any answer.
    Falls back to the item text if the language model returns nothing usable.
    """
    fallback = str(item_text or "").strip()
    schema = {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    }
    completion_guidance = (
        "The supplied source may be an abbreviated or truncated survey item, NOT its complete original wording.\n"
        "Write ONE complete, stand-alone question using only the meaning supported by the excerpt "
        "and its response options. Use the options to resolve the question format.\n"
        "Do not invent a missing premise, policy position, population, timeframe, scale anchor, "
        "or any other substantive detail. Do not imply your wording is verbatim from the source.\n"
        "If the excerpt and options are too ambiguous to form a faithful question, return an empty question string.\n"
    ) if source_incomplete else ""
    prompt = (
        "Rewrite the survey item below as ONE clear question addressed to a respondent ('you').\n"
        f"{completion_guidance}"
        "Requirements:\n"
        "1) Keep the item's exact meaning and topic; the question must be answerable with the listed options.\n"
        "2) Neutral wording: do not suggest, favour or frame toward any answer; no leading or loaded language.\n"
        "3) Plain conversational English, one sentence, no codes, abbreviations or survey jargon.\n"
        "4) Do not mention surveys, variables or models.\n\n"
        f"SURVEY ITEM:\n{fallback}\n\n"
        "RESPONSE OPTIONS:\n" + "\n".join(f"- {r}" for r in responses[:15]) + "\n"
    )
    try:
        resp = client.responses.create(
            model=model,
            input=prompt,
            text={"format": {"type": "json_schema", "name": "survey_question_wording", "schema": schema, "strict": True}},
        )
        q = str(json.loads(_get_output_text(resp)).get("question", "")).strip()
    except Exception:
        q = ""
    return q or fallback


def llm_craft_semantic_bridge_answer(
    client: OpenAI,
    persona_text: str,
    user_question: str,
    var_items: List[VarItem],
    bridge_rationale: str,
    bridge_items: List[Dict[str, object]],
    model: str,
) -> str:
    evidence_lines = []
    bridge_by_var = {str(x.get("variable", "")): x for x in bridge_items}
    for it in var_items:
        b = bridge_by_var.get(it.variable, {})
        evidence_lines.append(
            f"VAR={it.variable}\n"
            f"QUESTION_TEXT={it.question_text}\n"
            f"RESPONSE={it.response}\n"
            f"RELATION_TYPE={b.get('relation_type', '')}\n"
            f"CONFIDENCE={b.get('confidence', '')}\n"
            f"BRIDGE_RATIONALE={b.get('rationale', '')}\n"
        )

    prompt = (
        "Write a response as if you are a single human respondent.\n"
        "There was no direct survey item for the user's question, so the anchors below are indirect semantic evidence.\n"
        "Use them only to infer broad orientation, values, or likely stance. Do not treat them as direct facts.\n"
        "Requirements:\n"
        "1) Use first person ('I', 'my').\n"
        "2) Do not mention surveys, variables, models, embeddings, probabilities, files, or analysis.\n"
        "3) Stay consistent with the persona.\n"
        "4) Make the answer appropriately cautious when the bridge is weak, but still answer the user's question.\n"
        "5) Do not invent specific biographical facts beyond the persona and anchors.\n"
        "6) 2-7 sentences.\n\n"
        f"PERSONA:\n{persona_text}\n\n"
        f"USER QUESTION:\n{user_question}\n\n"
        f"OVERALL BRIDGE RATIONALE:\n{bridge_rationale}\n\n"
        "INDIRECT ANCHORS:\n" + "\n---\n".join(evidence_lines)
    )

    resp = client.responses.create(model=model, input=prompt, temperature=0.7)
    return _get_output_text(resp).strip()


# -----------------------------
# Qnet backend helpers
# -----------------------------

def blank_row(model) -> np.ndarray:
    """An all-missing model row ("" in every column).

    Object dtype, not a fixed-width string dtype: numpy 'U100' rows used to cut answer labels
    longer than 100 characters, so the truncated label matched no category and the answer was
    silently treated as missing.
    """
    return np.full(len(model.feature_names), "", dtype=object)


def get_possible_responses_from_model(model) -> Dict[str, List[str]]:
    """Return each model variable's original categorical support."""
    if hasattr(model, "possible_values"):
        return {
            str(k): [str(x) for x in v]
            for k, v in model.possible_values().items()
        }
    NULL = blank_row(model)
    resp = model.predict_distributions(NULL)
    out: Dict[str, List[str]] = {}
    for i, v in enumerate(model.feature_names):
        d = resp[i]
        try:
            out[v] = list(d.keys())
        except Exception:
            out[v] = []
    return out


def _model_sig_for_possible(qnet_path: str, model=None) -> str:
    if model is not None and hasattr(model, "cache_signature"):
        try:
            return str(model.cache_signature())
        except Exception:
            pass
    p = Path(qnet_path)
    try:
        st = os.stat(p)
        sig = f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}"
    except Exception:
        sig = f"{_abspath(qnet_path)}"
    return sig


def _possible_cache_path(qnet_path: str, assets_dir: str, model=None) -> str:
    assets_dir = _ensure_dir(assets_dir)
    p = Path(qnet_path)
    sig = _model_sig_for_possible(qnet_path, model=model)
    h = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12]
    base = p.name
    return str(Path(assets_dir) / f"{base}.possible.{h}.json")


def get_possible_responses_cached(model, qnet_path: str, assets_dir: str) -> Dict[str, List[str]]:
    cache_path = _possible_cache_path(qnet_path, assets_dir, model=model)
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
    NULL = blank_row(model)
    for v, val in assigns.items():
        j = idx_map.get(v)
        if j is not None:
            NULL[j] = str(val)
    return NULL


def qnet_conditional_distributions(
    model,
    NULL_cond: np.ndarray,
    target_vars: Optional[List[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """Backend-neutral conditional distributions.

    Native LSM can restrict inference to the selected target trees, avoiding a
    full all-column inference pass for each interactive question.
    """
    if hasattr(model, "backend_name"):
        return model.predict_distributions(NULL_cond, target_names=target_vars)
    resp = model.predict_distributions(NULL_cond)
    out = {model.feature_names[i]: resp[i] for i in range(len(resp))}
    if target_vars is not None:
        wanted = set(target_vars)
        out = {k: v for k, v in out.items() if k in wanted}
    return out


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
    x = blank_row(model)
    for v, val in state.items():
        j = idx_map.get(v)
        if j is not None:
            x[j] = str(val)
    return x


def build_pole_vector(model, pole_map: Dict[str, str], idx_map: Dict[str, int]) -> np.ndarray:
    x = blank_row(model)
    for v, val in pole_map.items():
        j = idx_map.get(v)
        if j is not None:
            x[j] = str(val)
    return x


def ideology_index_from_vectors(s: np.ndarray, sL: np.ndarray, sR: np.ndarray, model, dLR: float) -> float:
    if not np.isfinite(dLR) or dLR <= 0:
        return 0.0

    if hasattr(model, "distances_to_state"):
        dL, dR = model.distances_to_state(sL, sR, s)
    else:
        dL = model.qdistance(sL, s)
        dR = model.qdistance(sR, s)

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
