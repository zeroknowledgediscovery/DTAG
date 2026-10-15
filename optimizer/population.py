"""Participants: who the question set is optimized for.

A participants file (YAML) lists people as persona text and/or an explicit survey state::

    participants:
      - id: cm_rural_alabama
        text: "45-year-old white man living in open country ... strong Republican ..."
        state: {sex: male, age: "45.0", polviews: conservative, partyid: strong republican, ...}

* ``state`` pins the initial survey state exactly (labels must exist in the model; unknown ones
  are reported and dropped).
* ``text`` without ``state`` is decoded into a state by the LLM through DTAG's own persona
  decoding (cached). ``participants.decode: always`` re-decodes text even when a state is given.

Each participant's **direction** comes from the sign of its starting ideology I0: positive
participants should move further positive, negative ones further negative. Participants with
|I0| below ``neutral_band`` are reported but excluded from the objective.

Robustness: every simulated run starts from a perturbed copy of the participant's state:
each non-core variable is dropped with probability ``perturb.drop`` and, with probability
``perturb.resample``, re-drawn from the model's conditional distribution given the rest.
Core variables (default ``polviews``, ``partyid``) are never perturbed.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .dtag_bridge import JsonCache, World, decode_persona


def load(path: str) -> List[Dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    people = data.get("participants", data if isinstance(data, list) else [])
    out = []
    for i, p in enumerate(people):
        if not p.get("text") and not p.get("state"):
            raise SystemExit(f"participant #{i + 1} needs `text` or `state`")
        out.append({"id": str(p.get("id") or f"p{i + 1:02d}"), "text": str(p.get("text") or "").strip(),
                    "state": {str(k): str(v) for k, v in (p.get("state") or {}).items()},
                    "country": p.get("country"), "year": p.get("year")})
    return out


def prepare(world: World, people: List[Dict[str, Any]], decode: str, client: Any, llm_model: str,
            run: Dict[str, Any], cache: JsonCache, neutral_band: float, default_country: Optional[str],
            default_year: Optional[int], log=print) -> List[Dict[str, Any]]:
    """Resolve every participant to a validated starting state, I0 and a direction (+1/-1/0)."""
    out = []
    for p in people:
        source, dropped, rationale = "state", [], ""
        state = dict(p["state"])
        if p["text"] and (decode == "always" or (decode == "auto" and not state)):
            country, year = p.get("country") or default_country, p.get("year") or default_year
            k = cache.key("persona", world.model_path, p["text"], country, year, llm_model, run["max_assign"])
            d = cache.get(k)
            if d is None:
                d = decode_persona(world, client, p["text"], llm_model, run, country=country, year=year)
                cache.put(k, d)
            state = {**d["state"], **state} if decode == "auto" else dict(d["state"])
            source, dropped, rationale = "llm_decoded" if not p["state"] else "llm_decoded+state", d["dropped"], d["rationale"]
        valid, bad = world.valid(state)
        if not valid:
            raise SystemExit(f"participant {p['id']}: empty state after validation (dropped: {bad})")
        i0 = world.I(valid)
        direction = 0 if abs(i0) < neutral_band else (1 if i0 > 0 else -1)
        out.append({**p, "state": valid, "state_source": source, "dropped": dropped + bad,
                    "decode_rationale": rationale, "I0": i0, "direction": direction})
        log(f"  {p['id']:34s} I0={i0:+.4f}  group={'+' if direction > 0 else '-' if direction < 0 else 'neutral'}"
            f"  vars={len(valid)}{'  dropped=' + str(len(dropped + bad)) if dropped or bad else ''}  ({source})")
    groups = {d: sum(1 for p in out if p["direction"] == d) for d in (1, -1, 0)}
    if not groups[1] or not groups[-1]:
        raise SystemExit(f"Need participants on both sides of 0 (positive {groups[1]}, negative {groups[-1]}, "
                         f"neutral {groups[0]}); add participants or lower participants.neutral_band.")
    return out


def perturb(world: World, state: Dict[str, str], rng: random.Random, drop: float, resample: float,
            core: List[str]) -> Dict[str, str]:
    """Plausible variation of a starting state (see module docstring)."""
    st = {k: v for k, v in state.items() if k in core or rng.random() >= drop}
    redo = [k for k in st if k not in core and rng.random() < resample]
    if redo:
        rest = {k: v for k, v in st.items() if k not in redo}
        dists = world.dists(rest, redo)
        for k in redo:
            d = dists.get(k)
            if d:
                st[k] = rng.choices(list(d), weights=list(d.values()))[0]
    return st
