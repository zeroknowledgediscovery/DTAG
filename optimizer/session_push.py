"""Ideology-push suggestions for a live DTAG respondent session (used by the web app).

For the respondent's current survey state s, every askable, not-yet-answered survey item v is
scored exactly with the one-step geometry (optimizer.one_step_geometry):

    Delta_v(a | s) = I(s u {v=a}) - I(s)     for every native response a,
    mu_v = sum_a P(a | s, v) Delta_v(a | s)  (expected move from asking v).

The session's response mode decides what "moves the index" means for a suggestion:

* resp_mode "max" (the profiles' default): the session records the modal response, so asking v
  moves the index by exactly Delta_v(modal | s). Suggestions rank items by that value.
* resp_mode "draw": the response is sampled from P(a | s, v); suggestions rank by mu_v.

"up" is the item with the largest predicted move (toward the R pole, I increases), "down" the
smallest (toward L). Each suggestion carries a natural-language question written for exactly that
item (dtag_core.llm_craft_survey_question); asking it with target_variables=[v] makes the session
use that item, so the recorded and plotted ideology reflects the suggested move.

Askable items are opinion/attitude items (optimize_question_sets.askable): administrative codes,
demographics and factual behaviour items are never suggested. Pole-defining items are excluded
unless include_pole_items=True.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from optimizer.one_step_geometry import has_fast_extensions, native_one_step

DIRECTIONS = ("up", "down")


class SessionWorld:
    """Adapter giving a DTAGSession the World interface used by optimizer.one_step_geometry."""

    def __init__(self, session: Any):
        self.session = session
        self.m = session.model
        self.g = session.polar
        self.ctx = session.ctx
        self.text = session.ctx.var_map
        self.model_path = getattr(session.ctx, "model_path", "")
        self.map_path = getattr(session.ctx, "map_path", "")

    def valid(self, state: Dict[str, str]):
        ok, dropped = {}, []
        for k, v in state.items():
            if k in self.ctx.idx_map and str(v) in self.ctx.possible.get(k, []):
                ok[k] = str(v)
            else:
                dropped.append(f"{k}={v}")
        return ok, dropped

    def poles_summary(self) -> Dict[str, Any]:
        return {"file": getattr(self.g, "path", None), "items": len(self.g.left_map)}


def askable_items(session: Any, include_pole_items: bool = False) -> List[str]:
    """Opinion items that can be put to the respondent and are not answered yet."""
    from optimize_question_sets import askable

    ctx = session.ctx
    feat = set(ctx.feat)
    poles = set(session.polar.left_map) | set(session.polar.right_map)
    out = []
    for v in ctx.idx_map:
        if v in session.state or not ctx.possible.get(v) or v not in ctx.var_map:
            continue
        if v in poles and not include_pole_items:
            continue
        if askable(v, ctx.var_map.get(v, ""), feat):
            out.append(v)
    return sorted(out)


def _suggestion(row: Dict[str, Any], rows: List[Dict[str, Any]], direction: str, objective: str,
                current: float, state_full: bool) -> Dict[str, Any]:
    predicted = row["delta_modal"] if objective == "modal" else row["expected_delta"]
    answers = sorted(({"answer": r["answer"], "p": r["conditional_probability"], "delta": r["delta_I"]}
                      for r in rows), key=lambda a: -a["p"])
    return {
        "direction": direction,
        "variable": row["variable"],
        "survey_question": row["question_text"],
        "predicted_delta": predicted,
        "predicted_ideology": current + predicted,
        "objective": objective,
        "expected_delta": row["expected_delta"],
        "sd": row["sd"],
        "P_up": row["P_up"],
        "P_down": row["P_down"],
        "modal_answer": row["modal_answer"],
        "p_modal": row["p_modal"],
        "delta_modal": row["delta_modal"],
        "one_sided": bool(row["one_sided"]),
        "is_pole_item": bool(row["is_pole_item"]),
        "responses": answers,
        # Answering a new item when the state is at its size limit evicts the oldest
        # assignment, so the realized move can differ from the prediction.
        "exact": not state_full,
    }


def suggest(session: Any, *, include_pole_items: bool = False, craft: Optional[Any] = None) -> Dict[str, Any]:
    """Up/down suggestions for the session's current state.

    ``craft(variable, survey_question, responses) -> str`` writes the question shown to the user
    (the engine passes an LLM-backed, cached function); without it the survey text is used.
    """
    t0 = time.time()
    if not getattr(session, "ideology_enabled", False):
        reason = (getattr(session.polar, "disable_reason", None)
                  or "Ideology tracking is not available for this survey/profile.")
        return {"enabled": False, "reason": reason, "up": None, "down": None}
    with session.lock:
        resp_mode = str(getattr(session.config, "resp_mode", "max"))
        objective = "modal" if resp_mode == "max" else "expected"
        state = dict(session.state)
        only = askable_items(session, include_pole_items=include_pole_items)
        if not only:
            return {"enabled": True, "reason": "No askable survey items remain for this respondent.",
                    "up": None, "down": None, "objective": objective, "resp_mode": resp_mode,
                    "n_candidates": 0, "include_pole_items": include_pole_items}
        world = SessionWorld(session)
        res = native_one_step(world, state, exclude_poles=not include_pole_items, only=only)
        current = res.I_before
        state_full = len(state) + 1 > int(getattr(session.config, "state_keep", 10 ** 9))
    by_var: Dict[str, List[Dict[str, Any]]] = {}
    for r in res.rows:
        by_var.setdefault(r["variable"], []).append(r)
    key = "delta_modal" if objective == "modal" else "expected_delta"
    ranked = sorted(res.summary, key=lambda r: (r[key], r["variable"]))
    out: Dict[str, Any] = {
        "enabled": True, "reason": None, "objective": objective, "resp_mode": resp_mode,
        "current_ideology": current, "n_candidates": len(res.summary),
        "include_pole_items": include_pole_items, "fast_evaluator": has_fast_extensions(world),
    }
    picks = {"up": ranked[-1], "down": ranked[0]}
    for direction, row in picks.items():
        value = row[key]
        if (direction == "up" and value <= 0) or (direction == "down" and value >= 0):
            out[direction] = None
            out[f"{direction}_reason"] = f"No askable item is predicted to move the index {direction}."
            continue
        sug = _suggestion(row, by_var[row["variable"]], direction, objective, current, state_full)
        sug["question"] = (craft(row["variable"], row["question_text"], [a["answer"] for a in sug["responses"]])
                           if craft else row["question_text"])
        out[direction] = sug
    out["seconds"] = round(time.time() - t0, 3)
    return out


def predict_item(session: Any, variable: str) -> Dict[str, Any]:
    """One-step prediction for a single item at the current state (attached to a targeted ask)."""
    with session.lock:
        world = SessionWorld(session)
        res = native_one_step(world, dict(session.state), only=[variable])
    if not res.summary:
        return {}
    row = res.summary[0]
    return {"ideology_before": res.I_before, "expected_delta": row["expected_delta"],
            "delta_modal": row["delta_modal"], "modal_answer": row["modal_answer"]}
