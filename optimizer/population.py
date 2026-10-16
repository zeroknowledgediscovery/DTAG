"""Persona initialization, protected anchors, and conditional starting-state variation."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .dtag_bridge import REPO, JsonCache, World, decode_persona, sha256


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else REPO / p


def load(path: str) -> List[Dict[str, Any]]:
    data = yaml.safe_load(_path(path).read_text(encoding="utf-8")) or {}
    people = data.get("participants", data) if isinstance(data, dict) else data
    out = []
    for i, p in enumerate(people):
        description = str(p.get("text") or "").strip()
        if p.get("text_file"):
            description = _path(str(p["text_file"])).read_text(encoding="utf-8").strip()
        state = {str(k): str(v) for k, v in (p.get("state") or {}).items()}
        if not description and not state:
            raise SystemExit(f"participant #{i + 1} needs text, text_file, or state")
        def read_state_ref(ref):
            name, sep, key = str(ref).partition("#")
            document = json.loads(_path(name).read_text(encoding="utf-8"))
            entry = document[key] if sep else document
            return {str(k): str(v) for k, v in entry.get("state", {}).items()}

        expected = read_state_ref(p["expected_state_ref"]) if p.get("expected_state_ref") else {}
        # A core_state_ref pins only the explicitly stated political anchors
        # across survey waves; it does not apply 2024 demographic labels to 2018.
        core_expected = read_state_ref(p["core_state_ref"]) if p.get("core_state_ref") else {}
        out.append({"id": str(p.get("id") or f"p{i + 1:02d}"),
                    "text": description, "state": state, "expected_state": expected,
                    "core_expected": core_expected,
                    "country": p.get("country"), "year": p.get("year")})
    return out


def prepare(world: World, people: List[Dict[str, Any]], decode: str, client: Any, llm_model: str,
            run: Dict[str, Any], cache: JsonCache, neutral_band: float, default_country: Optional[str],
            default_year: Optional[int], log=print, protect_mapped: bool = True,
            core_variables: Optional[List[str]] = None,
            require_both_signs: bool = True,
            index_origin: str = "native") -> List[Dict[str, Any]]:
    """Resolve persona text to actual model labels. Protect decoded assignments by default.

    Optional expected-state references audit the LLM decode against the historical asset.
    Disagreement on the political core is fatal; other differences are logged and reported.
    """
    from .ideology_coordinates import empty_state_offset

    if index_origin not in ("native", "empty"):
        raise ValueError(f"Unknown ideology index origin {index_origin!r}")
    offset = empty_state_offset(world) if index_origin == "empty" else 0.0
    if index_origin == "empty":
        log(f"  ideology coordinate: I(x)-I(empty); I(empty)={offset:+.5f}; "
            f"neutral_band=±{neutral_band:g}")
    out = []
    core = list(core_variables or ["polviews", "partyid"])
    map_hash = sha256(Path(world.map_path))
    for p in people:
        source, dropped, rationale = "state", [], ""
        state = dict(p["state"])
        if p["text"] and (decode == "always" or (decode == "auto" and not state)):
            if client is None:
                raise SystemExit("Persona decoding needs a configured LLM backend.")
            country, year = p.get("country") or default_country, p.get("year") or default_year
            key = cache.key("persona", world.model_path, map_hash, p["text"], country, year,
                            llm_model, run["max_assign"], run["assign_prefilter"])
            d = cache.get(key)
            if d is None:
                d = decode_persona(world, client, p["text"], llm_model, run, country=country, year=year)
                cache.put(key, d)
            state = {**d["state"], **state} if decode == "auto" else dict(d["state"])
            source, dropped, rationale = "llm_decoded", d["dropped"], d["rationale"]
        # Cross-wave runner explicitly supplies the intended core assignments.
        # Validate labels in THIS model before overriding any incomplete LLM decode.
        core_expected = p.get("core_expected") or {}
        for k in core:
            if core_expected:
                if k not in core_expected:
                    raise SystemExit(f"participant {p['id']}: missing required anchor {k} in core_state_ref")
                wanted = core_expected[k]
                allowed = world.ctx.possible.get(k, [])
                if k not in world.ctx.idx_map or wanted not in allowed:
                    raise SystemExit(
                        f"participant {p['id']}: requested anchor {k}={wanted!r} "
                        f"is not an accepted survey label for this wave. "
                        f"Available labels: {allowed!r}")
                if state.get(k) != wanted:
                    log(f"  {p['id']}: pinning {k}={wanted!r} "
                        f"(decoded={state.get(k)!r})")
                state[k] = wanted
        valid, invalid = world.valid(state)
        if not valid:
            raise SystemExit(f"participant {p['id']}: empty state after validation ({invalid})")
        expected = p.get("expected_state") or {}
        mismatches = {k: {"expected": v, "actual": valid.get(k)} for k, v in expected.items()
                      if valid.get(k) != v}
        for k in core:
            if k in expected and valid.get(k) != expected[k]:
                raise SystemExit(f"participant {p['id']}: decoded political anchor {k}={valid.get(k)!r}; "
                                 f"expected {expected[k]!r}")
        if mismatches:
            log(f"  {p['id']}: {len(mismatches)} non-core expected-state differences")
        protected = sorted(set(valid) if protect_mapped else set(valid) & set(core))
        protected = sorted(set(protected) | (set(core) & set(valid)))
        if core_expected and not set(core).issubset(protected):
            raise SystemExit(
                f"participant {p['id']}: expected all core anchors protected, "
                f"missing {sorted(set(core) - set(protected))}")
        raw_index = float(world.I(valid))
        index = raw_index - offset
        direction = 0 if abs(index) < neutral_band else (1 if index > 0 else -1)
        out.append({**p, "state": valid, "protected": protected,
                    "protected_values": {k: valid[k] for k in protected},
                    "expected_mismatches": mismatches, "state_source": source,
                    "dropped": dropped + invalid, "decode_rationale": rationale,
                    "I_raw": raw_index, "I0": index, "I_empty": offset,
                    "index_origin": index_origin, "direction": direction})
        if index_origin == "empty":
            log(f"  {p['id']:34s} I_raw={raw_index:+.5f} "
                f"I_centered={index:+.5f} group={direction:+d} "
                f"vars={len(valid)} protected={len(protected)} ({source})")
        else:
            log(f"  {p['id']:34s} I0={index:+.4f} group={direction:+d} "
                f"vars={len(valid)} protected={len(protected)} ({source})")
    groups = {d: sum(p["direction"] == d for p in out) for d in (1, -1, 0)}
    if not groups[1] or not groups[-1]:
        details = "; ".join(
            f"{p['id']}: I0={p['I0']:+.5f}, "
            + ", ".join(f"{k}={p['state'].get(k)!r}" for k in core)
            for p in out)
        axis = "centered I(x)-I(empty)" if index_origin == "empty" else "raw I(x)"
        message = (f"Starting-sign coverage is insufficient using {axis}: "
                   f"groups={groups}. {details}. "
                   f"Check wave-specific pole geometry and persona decoding; "
                   f"political labels do not guarantee opposite model-index signs.")
        if require_both_signs:
            raise SystemExit(message)
        log(f"  WARNING: {message} Two-sign classification requires both "
            f"groups among the sampled starting states.")
    return out


def perturb(world: World, state: Dict[str, str], rng: random.Random, drop: float, resample: float,
            core: List[str]) -> Dict[str, str]:
    """Drop or resample only nonprotected assignments."""
    fixed = set(core)
    updated = {k: v for k, v in state.items() if k in fixed or rng.random() >= drop}
    redo = [k for k in updated if k not in fixed and rng.random() < resample]
    if redo:
        rest = {k: v for k, v in updated.items() if k not in redo}
        dists = world.dists(rest, redo)
        for k in redo:
            d = dists.get(k)
            if d:
                updated[k] = rng.choices(list(d), weights=list(d.values()))[0]
    for k in fixed & state.keys():
        assert updated[k] == state[k], f"protected starting assignment modified: {k}"
    return updated
