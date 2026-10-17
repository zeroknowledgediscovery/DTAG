"""Decision landscape of a live DTAG respondent: the model's predicted answers to every askable item.

At the respondent's current survey state s, every askable, not-yet-answered item v has a native
predicted answer distribution P(. | s, v). The landscape summarises each item by

* ``settled`` = 1 - H(P) / log(k): how decided the twin is on v (1 = one answer certain, 0 = uniform);
* ``modal`` / ``p_modal``: its most likely answer;
* ``lean`` (surveys with an ideology index): Delta_v(modal | s) = I(s u {v=modal}) - I(s), the move of the
  index if the twin answered v as it most likely would (sign: toward the R (+) or L (-) pole);
* ``shift``: Jensen-Shannon divergence (bits, in [0, 1]) between P(. | s, v) now and at the previous
  snapshot, i.e. how much the last interaction(s) changed the predicted answer to v.

Answered items are ``anchored``: they are part of the state and no longer predicted. Items are grouped
into topics (optimizer.topics) for display.

These are the survey model's conditional predictions for the respondent's digital twin, not the
person's reasoning.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from optimizer.session_push import SessionWorld, askable_items, scored
from optimizer.topics import ORDER, topics_for

SHIFT_EPS = 1e-4  # JS divergence (bits) above which an item counts as "moved"


def _settled(p: Dict[str, float]) -> float:
    q = [x for x in p.values() if x > 0]
    if len(p) <= 1 or not q:
        return 1.0
    h = -sum(x * math.log(x) for x in q)
    return max(0.0, 1.0 - h / math.log(len(p)))


def js_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon divergence in bits (0 = identical, 1 = disjoint)."""
    out = 0.0
    for a in set(p) | set(q):
        x, y = p.get(a, 0.0), q.get(a, 0.0)
        m = (x + y) / 2
        if x > 0:
            out += 0.5 * x * math.log2(x / m)
        if y > 0:
            out += 0.5 * y * math.log2(y / m)
    return max(0.0, out)


def snapshot(session: Any) -> Dict[str, Any]:
    """Predicted answer distributions and summaries for every askable item at the current state."""
    from optimizer.one_step_geometry import native_distributions

    with session.lock:
        state = dict(session.state)
        items = askable_items(session, include_pole_items=True)
        lean: Dict[str, float] = {}
        if getattr(session, "ideology_enabled", False):
            res = scored(session)
            dists: Dict[str, Dict[str, float]] = {}
            for r in res.rows:
                dists.setdefault(r["variable"], {})[str(r["answer"])] = float(r["conditional_probability"])
            lean = {r["variable"]: float(r["delta_modal"]) for r in res.summary}
            ideology: Optional[float] = float(res.I_before)
        else:
            dists = native_distributions(SessionWorld(session), state, items)
            ideology = None
        var_map = session.ctx.var_map
        step = int(session.query_count)
    out: Dict[str, Dict[str, Any]] = {}
    for v in items:
        p = dists.get(v) or {}
        tot = sum(p.values())
        if tot <= 0:
            continue
        p = {a: x / tot for a, x in p.items()}
        modal = max(p, key=lambda a: (p[a], a))
        out[v] = {"dist": p, "settled": _settled(p), "modal": modal, "p_modal": p[modal], "lean": lean.get(v)}
    topics = topics_for(list(out) + list(state), var_map)
    return {"step": step, "state": state, "items": out, "topics": topics, "ideology": ideology}


def _short(text: str, n: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def lean_scale_of(snap: Dict[str, Any]) -> Optional[float]:
    """90th percentile of |lean| (colour scale; fixed per session so colours stay comparable)."""
    leans = sorted(abs(r["lean"]) for r in snap["items"].values() if r["lean"] is not None)
    return leans[int(0.9 * (len(leans) - 1))] or None if leans else None


def build_view(cur: Dict[str, Any], prev: Optional[Dict[str, Any]], var_map: Dict[str, str],
               history: List[Dict[str, Any]], lean_scale: Optional[float] = None) -> Dict[str, Any]:
    """Compact payload for the web view: items by topic, anchored items, shift vs ``prev``."""
    topics = cur["topics"]
    prev_items = prev["items"] if prev else {}
    prev_state = prev["state"] if prev else {}
    items = []
    for v, r in cur["items"].items():
        shift = js_divergence(r["dist"], prev_items[v]["dist"]) if v in prev_items else None
        items.append({"v": v, "t": topics.get(v, "Other"), "q": _short(var_map.get(v, "")), "s": round(r["settled"], 4),
                      "m": r["modal"], "p": round(r["p_modal"], 4),
                      "l": None if r["lean"] is None else round(r["lean"], 6),
                      "d": None if shift is None else round(shift, 6)})
    order = {t: i for i, t in enumerate(ORDER)}
    items.sort(key=lambda x: (order.get(x["t"], len(order)), x["v"].lower()))
    new_vars = [v for v, a in cur["state"].items() if prev is not None and prev_state.get(v) != a]
    anchored = [{"v": v, "t": topics.get(v, "Other"), "q": _short(var_map.get(v, "")), "a": a, "new": v in new_vars}
                for v, a in cur["state"].items()]
    anchored.sort(key=lambda x: (order.get(x["t"], len(order)), x["v"].lower()))

    moved = [x for x in items if x["d"] is not None and x["d"] > SHIFT_EPS]
    by_topic: Dict[str, Dict[str, Any]] = {}
    for x in items:
        t = by_topic.setdefault(x["t"], {"name": x["t"], "n": 0, "settled": 0.0, "shift": 0.0, "moved": 0, "anchored": 0})
        t["n"] += 1
        t["settled"] += x["s"]
        t["shift"] += x["d"] or 0.0
        t["moved"] += int(x["d"] is not None and x["d"] > SHIFT_EPS)
    for a in anchored:
        by_topic.setdefault(a["t"], {"name": a["t"], "n": 0, "settled": 0.0, "shift": 0.0, "moved": 0, "anchored": 0})["anchored"] += 1
    topic_list = []
    for name in sorted(by_topic, key=lambda t: order.get(t, len(order))):
        t = by_topic[name]
        t["settled"] = round(t["settled"] / t["n"], 4) if t["n"] else None
        t["shift"] = round(t["shift"], 6)
        topic_list.append(t)
    summary = {
        "n_items": len(items),
        "n_moved": len(moved),
        "total_shift": round(sum(x["d"] for x in moved), 6),
        "top_topics": [t["name"] for t in sorted(topic_list, key=lambda t: -t["shift"]) if t["moved"]][:3],
        "top_items": [{k: x[k] for k in ("v", "t", "q", "d", "m")} for x in sorted(moved, key=lambda x: -x["d"])[:5]],
        "mean_settled": round(sum(x["s"] for x in items) / len(items), 4) if items else None,
    }
    return {
        "enabled": True,
        "step": cur["step"],
        "since_step": prev["step"] if prev else None,
        "ideology": cur["ideology"],
        "has_lean": cur["ideology"] is not None,
        "lean_scale": lean_scale,
        "shift_eps": SHIFT_EPS,
        "topics": topic_list,
        "items": items,
        "anchored": anchored,
        "new_anchored": new_vars,
        "summary": summary,
        "history": history,
    }
