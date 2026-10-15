"""Everything the optimizer needs from DTAG, using DTAG's own code paths.

* the native LSM model (installed under DTAG's model cache, downloaded if missing),
* the canonical semantic map and the (wave-specific) ideology poles,
* ideology I(s) and conditional answer distributions P(variable | state),
* question -> survey variables exactly as the web app maps a question (lexical prefilter +
  LLM variable selection), and persona text -> survey state exactly as a session decodes it.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import pipeline as core  # noqa: E402
from dtag_paths import model_root as dtag_model_root  # noqa: E402
from dtag_session import ModelContext, build_polar_geometry  # noqa: E402
from model_backend import load_model  # noqa: E402

DEFAULT_POLES = REPO / "assets" / "polar_vectors" / "polar_vectors.csv"
RUN_DEFAULTS = {"k": 50, "prefilter": 200, "min_map_score": 1.0, "max_assign": 50, "assign_prefilter": 500}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_map(model_key: str) -> Path:
    sys.path.insert(0, str(REPO / "scripts"))
    from dtag_engine import canonical_map_key, map_inventory

    mk = canonical_map_key(model_key)
    if not mk:
        raise SystemExit(f"No canonical semantic map for {model_key}")
    return Path(map_inventory()[mk])


def ensure_model(model_key: str, root: Optional[str], download: bool = True) -> Path:
    """Path to the installed native model, downloading it from the public release if needed."""
    import fetch_models

    base = Path(root).expanduser().resolve() if root else dtag_model_root()
    if not fetch_models.installed(base, model_key):
        if not download:
            raise SystemExit(f"Model {model_key} is not installed under {base} (enable download or run "
                             f"`python scripts/fetch_models.py {model_key}`).")
        print(f"Downloading {model_key} into {base} ...", flush=True)
        fetch_models.fetch_one(base, fetch_models.load_manifest(), model_key)
    return base / model_key


def model_record(model_key: str) -> Dict[str, Any]:
    try:
        import fetch_models

        m = fetch_models.load_manifest()
        rec = dict(m["models"].get(model_key) or {})
        rec["release"] = m.get("release")
        return rec
    except Exception as e:  # offline: provenance still records the key
        return {"error": str(e)}


class World:
    """Native model + map + poles. One instance per worker process."""

    def __init__(self, model_path: str, map_path: str, poles: str, assets_dir: str):
        self.model_path, self.map_path = str(model_path), str(map_path)
        self.m = load_model(self.model_path)
        self.ctx = ModelContext(self.m, self.model_path, self.map_path, assets_dir=assets_dir)
        self.g = build_polar_geometry(self.ctx, str(poles))
        if not self.g.enabled:
            raise SystemExit(f"Ideology poles unavailable for this model: {self.g.disable_reason}")
        self.text: Dict[str, str] = {}
        with open(self.map_path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.text[r["variable"]] = (r.get("question_text_filled") or r.get("question_text") or "").strip()

    # -- model ---------------------------------------------------------------------
    def valid(self, state: Dict[str, str]) -> Tuple[Dict[str, str], List[str]]:
        ok, dropped = {}, []
        for k, v in state.items():
            if k in self.ctx.idx_map and str(v) in self.ctx.possible.get(k, []):
                ok[k] = str(v)
            else:
                dropped.append(f"{k}={v}")
        return ok, dropped

    def I(self, state: Dict[str, str]) -> float:
        X = core.build_full_vector_from_state(self.m, state, self.ctx.idx_map)
        return float(core.ideology_index_from_vectors(X, self.g.sL, self.g.sR, self.m, dLR=self.g.dLR))

    def dists(self, state: Dict[str, str], variables: Sequence[str]) -> Dict[str, Dict[str, float]]:
        N = core.build_NULL_with_assignments(self.m, dict(state), self.ctx.idx_map)
        out = {}
        for v, d in core.qnet_conditional_distributions(self.m, N, target_vars=list(variables)).items():
            d = {a: p for a, p in d.items() if a in self.ctx.possible.get(v, []) and p > 0}
            s = sum(d.values())
            if s > 0:
                out[v] = {a: p / s for a, p in d.items()}
        return out

    def poles_summary(self) -> Dict[str, Any]:
        return {"file": Path(self.g.path).name, "items": len(self.g.left_map), "sha256": sha256(Path(self.g.path))}


# ------------------------------------------------------------------ language steps (DTAG code)

def map_question(world: World, client: Any, question: str, model_name: str, run: Dict[str, Any]) -> Dict[str, Any]:
    """Map one question to survey variables the way a DTAG session's direct path does."""
    ctx = world.ctx
    cands = core.lexical_prefilter(ctx.var_map, question, top_n=int(run["prefilter"]), min_score=float(run["min_map_score"]))
    if not cands:
        return {"variables": [], "mapping": "no_lexical_candidate", "rationale": ""}
    variables, rationale = core.llm_select_variables(
        client=client, question=question, candidates_block=core.candidates_text(cands), k=int(run["k"]), model=model_name)
    variables = [v for v in variables if v in ctx.var_map and v in ctx.idx_map]
    return {"variables": variables, "mapping": "direct" if variables else "llm_no_relevant_variable",
            "rationale": rationale, "lexical_candidates": len(cands)}


def decode_persona(world: World, client: Any, text: str, model_name: str, run: Dict[str, Any],
                   country: Optional[str] = None, year: Optional[int] = None) -> Dict[str, Any]:
    """Persona text -> survey state, mirroring DTAGSession initialization (country/year context,
    lexical offer list, LLM assignment, validation against the model's support)."""
    ctx = world.ctx
    persona = text
    if country:
        persona = f"{persona}\nCountry context: {country}"
    if year is not None:
        persona = f"{persona}\nSurvey year: {year}"
    p_toks = set(core._tokenize(persona))
    scored = []
    for v in ctx.feat:
        if ctx.possible.get(v):
            scored.append((len(p_toks & set(core._tokenize(core._norm(ctx.var_map.get(v, v))))), v))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    allowed = {v: ctx.possible[v] for _, v in scored[: max(1, int(run["assign_prefilter"]))]}
    assigns, rationale = core.llm_persona_to_assignments(
        client=client, persona_text=persona, allowed=allowed, max_assign=int(run["max_assign"]), model=model_name)
    state, dropped = world.valid(assigns)
    return {"state": state, "dropped": dropped, "rationale": rationale}


class JsonCache:
    """Tiny persistent cache for LLM-derived results (question mappings, decoded personas)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, Any] = json.loads(self.path.read_text()) if self.path.is_file() else {}

    @staticmethod
    def key(*parts: Any) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def get(self, k: str) -> Any:
        return self.data.get(k)

    def put(self, k: str, v: Any) -> None:
        self.data[k] = v
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False))
        os.replace(tmp, self.path)
