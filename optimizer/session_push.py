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
smallest (toward L). Each suggestion carries a natural-language question written for that item
(dtag_core.llm_craft_survey_question). Two modes decide what happens to that question:

* mode="realistic" (default): the question is asked like any typed question. The normal mapping
  (lexical prefilter + LLM selection) chooses the survey items S(q) that are updated, which may or
  may not be the optimizer's item. The prediction shown is for the item alone; the outcome
  (mapped items, hit/miss, realized change) is recorded honestly.
* mode="validated": for the top N items per direction the question's mapping is dry-run first
  (DTAGSession.map_question). Candidates whose mapping misses the item are dropped; the rest are
  ranked by the exact joint change of all mapped items (predict_joint), and the question is then
  answered through that validated mapping, so the realized change equals the prediction.
* mode="direct" ("push" in the UI): the question is answered through exactly the optimizer's
  item, skipping the mapping, so the realized change equals the prediction for that item.

Askable items are opinion/attitude items (optimize_question_sets.askable): administrative codes,
demographics and factual behaviour items are never suggested. Pole-defining items are excluded
unless include_pole_items=True.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from concurrent.futures import ThreadPoolExecutor

from optimizer.one_step_geometry import has_fast_extensions, native_one_step, strict_native_index

DIRECTIONS = ("up", "down")
MODES = ("realistic", "validated", "direct")


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


def scored(session: Any):
    """One-step geometry of every askable item (pole items included) at the session's current state.

    Cached on the session per state, so the push suggestions and the decision landscape share one
    native pass. Call with ``session.lock`` held or accept that the state may move underneath.
    """
    with session.lock:
        key = (tuple(sorted(session.state.items())), id(session.polar))
        hit = getattr(session, "_one_step_cache", None)
        if hit is not None and hit[0] == key:
            return hit[1]
        only = askable_items(session, include_pole_items=True)
        res = native_one_step(SessionWorld(session), dict(session.state), only=only)
        session._one_step_cache = (key, res)
        return res


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


def predict_joint(session: Any, variables: List[str]) -> Dict[str, Any]:
    """Exact change of I if the session answered ``variables`` now with resp_mode "max".

    Mirrors DTAGSession._answer_with_variables: the same native conditional distributions given
    the current state, the most likely response per item, only valid labels written, then I of the
    updated state. (Eviction at the state-size limit is not modelled; see ``exact``.)
    """
    import dtag_core as core

    with session.lock:
        model, ctx = session.model, session.ctx
        state = dict(session.state)
        world = SessionWorld(session)
        I0 = strict_native_index(world, state)
        row = core.build_NULL_with_assignments(model, state, ctx.idx_map)
        dists = core.qnet_conditional_distributions(model, row, target_vars=list(variables))
        respmap, _ = core.responses_for_vars_from_distributions(dists, list(variables), mode="max")
        updates = {v: respmap[v] for v in variables if v in respmap and respmap[v] in ctx.possible.get(v, [])}
        I1 = strict_native_index(world, {**state, **updates})
        state_full = len({**state, **updates}) > int(getattr(session.config, "state_keep", 10 ** 9))
    return {"ideology_before": I0, "delta": I1 - I0, "answers": updates, "exact": not state_full}


def suggest(session: Any, *, include_pole_items: bool = False, craft: Optional[Any] = None,
            mode: str = "realistic", map_question: Optional[Any] = None, n_validate: int = 5) -> Dict[str, Any]:
    """Up/down suggestions for the session's current state.

    ``craft(variable, survey_question, responses) -> str`` writes the question shown to the user
    (the engine passes an LLM-backed, cached function); without it the survey text is used.
    ``map_question(question) -> [variables]`` (validated mode) returns the normal question->item
    mapping; the engine passes a cached DTAGSession.map_question.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
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
        res_all = scored(session)
        keep = set(only)
        rows = [r for r in res_all.rows if r["variable"] in keep]
        summary = [r for r in res_all.summary if r["variable"] in keep]
        current = res_all.I_before
        state_full = len(state) + 1 > int(getattr(session.config, "state_keep", 10 ** 9))
    by_var: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_var.setdefault(r["variable"], []).append(r)
    key = "delta_modal" if objective == "modal" else "expected_delta"
    ranked = sorted(summary, key=lambda r: (r[key], r["variable"]))
    out: Dict[str, Any] = {
        "enabled": True, "reason": None, "objective": objective, "resp_mode": resp_mode, "mode": mode,
        "current_ideology": current, "n_candidates": len(summary),
        "include_pole_items": include_pole_items, "fast_evaluator": has_fast_extensions(world),
    }

    def word(row: Dict[str, Any]) -> str:
        answers = [r["answer"] for r in by_var[row["variable"]]]
        return craft(row["variable"], row["question_text"], answers) if craft else row["question_text"]

    for direction in DIRECTIONS:
        sign = 1 if direction == "up" else -1
        cands = [r for r in (ranked[::-1] if direction == "up" else ranked) if sign * r[key] > 0]
        if not cands:
            out[direction] = None
            out[f"{direction}_reason"] = f"No askable item is predicted to move the index {direction}."
            continue
        if mode in ("realistic", "direct"):
            row = cands[0]
            sug = _suggestion(row, by_var[row["variable"]], direction, objective, current, state_full)
            sug.update({"question": word(row), "mode": mode, "mapped_variables": None})
            out[direction] = sug
            continue
        # validated: word + dry-run the normal mapping for the top candidates (LLM calls in parallel)
        top = cands[:max(1, int(n_validate))]
        with ThreadPoolExecutor(max_workers=min(8, len(top))) as ex:
            questions = list(ex.map(word, top))
            mappings = list(ex.map(lambda q: list(map_question(q)) if map_question else [], questions))
        checked, best = [], None
        for row, q, mapped in zip(top, questions, mappings):
            hit = row["variable"] in mapped
            rec = {"variable": row["variable"], "question": q, "mapped_variables": mapped, "hit": hit}
            if hit:
                if objective == "modal":
                    joint = predict_joint(session, mapped)
                    rec.update({"predicted_delta": joint["delta"], "answers": joint["answers"],
                                "exact": joint["exact"], "basis": "exact joint change of all mapped items"})
                else:
                    mu = {r["variable"]: r["expected_delta"] for r in summary}
                    rec.update({"predicted_delta": sum(mu.get(v, 0.0) for v in mapped), "answers": None,
                                "exact": False, "basis": "sum of the mapped items' expected changes (approx.)"})
                if sign * rec["predicted_delta"] > 0 and (best is None or sign * rec["predicted_delta"] > sign * best[1]["predicted_delta"]):
                    best = (row, rec)
            checked.append(rec)
        out[f"{direction}_checked"] = checked
        if best is None:
            out[direction] = None
            out[f"{direction}_reason"] = (f"None of the top {len(top)} items' questions maps back to its item while "
                                          f"moving the index {direction}.")
            continue
        row, rec = best
        sug = _suggestion(row, by_var[row["variable"]], direction, objective, current, state_full)
        sug.update({"question": rec["question"], "mode": mode, "mapped_variables": rec["mapped_variables"],
                    "item_delta": sug["predicted_delta"], "predicted_delta": rec["predicted_delta"],
                    "predicted_ideology": current + rec["predicted_delta"], "joint_answers": rec["answers"],
                    "exact": rec["exact"], "basis": rec["basis"]})
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
