"""Exact one-step survey-item response geometry: which question moves the ideology index most?

Given a native LSM (any survey/wave), its ideology poles, and the responses already known
for a respondent (a partial state ``s``), this module enumerates EVERY candidate variable
``v`` and EVERY valid native answer ``a`` and computes

    Delta_v(a | s) = I(s u {v=a}) - I(s)                  exact displacement (raw == centered)
    P(a | s, v)                                            native conditional probability
    mu_v(s)        = sum_a P(a|s,v) Delta_v(a|s)           expected displacement of ASKING v
    sigma_v(s)^2   = sum_a P(a|s,v) (Delta_v(a|s) - mu_v)^2
    delta_plus_v   = max_a Delta_v(a|s),  delta_minus_v = min_a Delta_v(a|s)
    P_up_v         = sum_{a: Delta>0} P(a|s,v),  P_down_v = sum_{a: Delta<0} P(a|s,v)

and returns the extremes:

* ``argmax_mu`` / ``argmin_mu``         -- the question to ASK to push the index right / left
                                          in expectation (answers are drawn by the model);
* ``argmax_delta`` / ``argmin_delta``   -- the (question, answer) pair with the largest
                                          right / left displacement, with its probability
                                          (a best case: the asker cannot choose the answer);
* ``argmax_p_up`` / ``argmax_p_down``   -- the question most likely to move the index right / left.

Positive displacement = toward the right pole. J(s) = I(s) - I(empty) only shifts the origin,
so every displacement is identical in raw and centered coordinates; J values are reported
for convenience.

Python use (native)::

    from optimizer.dtag_bridge import World, DEFAULT_POLES, canonical_map, ensure_model
    from optimizer.one_step_geometry import native_one_step

    world = World(str(ensure_model("gss/gss_2018", None)), str(canonical_map("gss/gss_2018")),
                  str(DEFAULT_POLES), "outputs/native_cache")
    res = native_one_step(world, {"polviews": "conservative", "partyid": "strong republican"},
                          exclude_poles=True)
    res.extremes["argmax_mu"]   # {'variable': ..., 'expected_delta': ..., ...}

Command line::

    python -m optimizer.one_step_geometry --model gss/gss_2018 --persona-ref CM \\
        --exclude-poles --workers 4 --out outputs/one_step/cm

    python -m optimizer.one_step_geometry --model gss/gss_2018 \\
        --state polviews="extremely liberal" --state partyid="strong democrat" --top 15

The core (:func:`one_step_geometry`) is model-agnostic: it takes an index function and a
conditional-distribution function, so it can be tested or reused without the native runtime.
No pruning or approximation is done. A full GSS 2018 sweep (~7k pairs) takes ~4-5 s with the
incremental native evaluator (Runtime.extension_distances: pole predictions cached, only trees that
split on the added item re-evaluated; bit-identical to the full computation), ~3 min without it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

State = Dict[str, str]
IndexFn = Callable[[Sequence[State]], List[float]]          # batch of states -> I values
DistFn = Callable[[State, Sequence[str]], Dict[str, Dict[str, float]]]

ROW_FIELDS = ["variable", "question_text", "answer", "conditional_probability", "is_pole_item",
              "I_before", "I_after", "J_before", "J_after", "delta_I"]
SUMMARY_FIELDS = ["variable", "question_text", "is_pole_item", "n_answers", "expected_delta", "sd",
                  "P_up", "P_down", "P_zero", "one_sided", "delta_plus", "answer_plus", "p_answer_plus",
                  "delta_minus", "answer_minus", "p_answer_minus", "range", "modal_answer", "p_modal",
                  "delta_modal"]
ZERO = 1e-12  # |Delta| below this counts as no movement


@dataclass
class OneStepResult:
    I_before: float
    J_before: Optional[float]
    I_empty: Optional[float]
    rows: List[Dict[str, Any]]          # one per (variable, answer)
    summary: List[Dict[str, Any]]       # one per variable, sorted by expected_delta descending
    extremes: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)

    def top(self, key: str, k: int = 10, reverse: bool = True) -> List[Dict[str, Any]]:
        """Top-k variables by a summary column (e.g. 'expected_delta', 'P_up', 'range')."""
        return sorted(self.summary, key=lambda r: (r[key], r["variable"]), reverse=reverse)[:k]


# --------------------------------------------------------------------------- core (pure)

def summarize_variable(variable: str, rows: Sequence[Mapping[str, Any]], text: str = "",
                       is_pole: bool = False) -> Dict[str, Any]:
    """Per-variable statistics from its response-level rows (one row per answer)."""
    p = [float(r["conditional_probability"]) for r in rows]
    d = [float(r["delta_I"]) for r in rows]
    imax = max(range(len(d)), key=lambda i: (d[i], p[i]))
    imin = min(range(len(d)), key=lambda i: (d[i], -p[i]))
    imod = max(range(len(p)), key=lambda i: p[i])
    mu = sum(pi * di for pi, di in zip(p, d))
    var = sum(pi * (di - mu) ** 2 for pi, di in zip(p, d))
    up = sum(pi for pi, di in zip(p, d) if di > ZERO)
    down = sum(pi for pi, di in zip(p, d) if di < -ZERO)
    return {"variable": variable, "question_text": text, "is_pole_item": bool(is_pole), "n_answers": len(rows),
            "expected_delta": mu, "sd": math.sqrt(max(var, 0.0)), "P_up": up, "P_down": down,
            "P_zero": max(0.0, 1.0 - up - down),
            # every answer moves the index the same way (or not at all): a question effect,
            # not an answer-content effect
            "one_sided": (min(d) >= -ZERO or max(d) <= ZERO) and max(abs(x) for x in d) > ZERO,
            "delta_plus": d[imax], "answer_plus": rows[imax]["answer"], "p_answer_plus": p[imax],
            "delta_minus": d[imin], "answer_minus": rows[imin]["answer"], "p_answer_minus": p[imin],
            "range": d[imax] - d[imin], "modal_answer": rows[imod]["answer"], "p_modal": p[imod],
            "delta_modal": d[imod]}


def extremes_of(summary: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """argmax/argmin of mu, Delta, P_up and P_down over a per-variable summary."""
    if not summary:
        return {}
    keep = ("variable", "question_text", "is_pole_item", "expected_delta", "sd", "P_up", "P_down", "one_sided")

    def var_rec(r):
        return {k: r[k] for k in keep}

    def pick(key, sign):
        return max(summary, key=lambda r: (sign * r[key], r["variable"]))

    amax_d, amin_d = pick("delta_plus", 1), pick("delta_minus", -1)
    return {
        "argmax_mu": var_rec(pick("expected_delta", 1)),
        "argmin_mu": var_rec(pick("expected_delta", -1)),
        "argmax_delta": {**var_rec(amax_d), "answer": amax_d["answer_plus"], "delta": amax_d["delta_plus"],
                         "probability": amax_d["p_answer_plus"]},
        "argmin_delta": {**var_rec(amin_d), "answer": amin_d["answer_minus"], "delta": amin_d["delta_minus"],
                         "probability": amin_d["p_answer_minus"]},
        "argmax_p_up": var_rec(pick("P_up", 1)),
        "argmax_p_down": var_rec(pick("P_down", 1)),
    }


def one_step_geometry(state: Mapping[str, str], candidates: Mapping[str, Sequence[str]],
                      index_fn: IndexFn, dist_fn: DistFn, *, I_empty: Optional[float] = None,
                      text: Optional[Mapping[str, str]] = None,
                      pole_items: Iterable[str] = (),
                      extension_fn: Optional[Callable[[State, Sequence[Tuple[str, str]]],
                                                      Tuple[float, List[float]]]] = None) -> OneStepResult:
    """Exhaustive one-step enumeration for an arbitrary model.

    state       -- answers already known (variable -> label); never re-assigned.
    candidates  -- variable -> its valid answer labels (the variables you may ask).
    index_fn    -- maps a batch of states to their ideology index I.
    dist_fn     -- (state, variables) -> {variable: {label: P}} conditional distributions.
    I_empty     -- I of the empty state; if given, centered J values are filled in.
    extension_fn -- optional fast path: (state, [(v, a), ...]) -> (I(state), [I(state+{v=a}), ...]);
                    must agree with index_fn. Used instead of index_fn when given.
    """
    state = {str(k): str(v) for k, v in state.items()}
    text, poles = dict(text or {}), set(pole_items)
    cand = {v: [str(a) for a in labels] for v, labels in candidates.items() if v not in state and labels}
    variables = sorted(cand)
    pairs = [(v, a) for v in variables for a in cand[v]]
    if extension_fn is not None:
        I0, after = extension_fn(state, pairs)
        I0 = float(I0)
    else:
        I0 = float(index_fn([state])[0])
        after = index_fn([{**state, v: a} for v, a in pairs])
    if len(after) != len(pairs):
        raise ValueError("index_fn returned the wrong number of values")
    dists = dist_fn(state, variables)
    J0 = None if I_empty is None else I0 - I_empty
    by_var: Dict[str, List[Dict[str, Any]]] = {v: [] for v in variables}
    for (v, a), I1 in zip(pairs, after):
        I1 = float(I1)
        if not math.isfinite(I1):
            raise FloatingPointError(f"Nonfinite index for {v}={a}")
        dv = dists.get(v) or {}
        z = sum(float(dv.get(b, 0.0)) for b in cand[v])
        p = float(dv.get(a, 0.0)) / z if z > 0 else float("nan")
        by_var[v].append({"variable": v, "question_text": text.get(v, ""), "answer": a,
                          "conditional_probability": p, "is_pole_item": v in poles,
                          "I_before": I0, "I_after": I1, "J_before": J0,
                          "J_after": None if I_empty is None else I1 - I_empty, "delta_I": I1 - I0})
    rows = [r for v in variables for r in by_var[v]]
    summary = [summarize_variable(v, by_var[v], text.get(v, ""), v in poles) for v in variables]
    summary.sort(key=lambda r: (-r["expected_delta"], r["variable"]))
    return OneStepResult(I0, J0, I_empty, rows, summary, extremes_of(summary),
                         {"n_variables": len(variables), "n_pairs": len(pairs)})


# --------------------------------------------------------------------------- native adapters

def state_row(world, state: Mapping[str, str]):
    """Full model row for a partial state (labels of any length; see dtag_core.blank_row)."""
    import dtag_core as core
    return core.build_full_vector_from_state(world.m, dict(state), world.ctx.idx_map)


def strict_native_index(world, state: Mapping[str, str]) -> float:
    """I(s) from the native qdistance; raises instead of World.I's silent 0.0 on nonfinite values."""
    m, g = world.m, world.g
    x = state_row(world, state)
    if hasattr(m, "distances_to_state"):
        dl, dr = m.distances_to_state(g.sL, g.sR, x)
    else:
        dl, dr = m.qdistance(g.sL, x), m.qdistance(g.sR, x)
    dl, dr, dlr = float(dl), float(dr), float(g.dLR)
    if not (math.isfinite(dl) and math.isfinite(dr) and math.isfinite(dlr) and dlr > 0):
        raise FloatingPointError(f"Nonfinite native distance for {dict(state)}")
    return (dl - dr) / dlr


def native_extension_indices(world, state: Mapping[str, str],
                             pairs: Sequence[Tuple[str, str]]) -> Tuple[float, List[float]]:
    """I(s) and I(s u {v=a}) for every pair in one native call (incremental; exact).

    Only trees that split on v are re-evaluated for each pair, and pole predictions are cached,
    so a full one-step sweep is far cheaper than calling strict_native_index per state.
    Raises on nonfinite distances, like strict_native_index.
    """
    m, g = world.m, world.g
    x = state_row(world, state)
    dl0, dr0, dl, dr = m.extension_distances(g.sL, g.sR, x, list(pairs))
    dlr = float(g.dLR)
    vals = [dl0, dr0, dlr] + dl + dr
    if not (all(math.isfinite(v) for v in vals) and dlr > 0):
        raise FloatingPointError(f"Nonfinite native distance in extensions of {dict(state)}")
    return (dl0 - dr0) / dlr, [(a - b) / dlr for a, b in zip(dl, dr)]


def has_fast_extensions(world) -> bool:
    return bool(getattr(world.m, "has_extension_distances", False))


def native_distributions(world, state: Mapping[str, str], variables: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """Unfiltered native P(. | s, v) restricted to each variable's valid labels."""
    import dtag_core as core
    raw = core.qnet_conditional_distributions(world.m, state_row(world, state), target_vars=list(variables))
    return {v: {str(a): float(p) for a, p in (raw.get(v) or {}).items()
                if str(a) in world.ctx.possible.get(v, [])} for v in variables}


_POOL_WORLD = None


def _pool_init(world_args):
    global _POOL_WORLD
    from optimizer.dtag_bridge import World
    _POOL_WORLD = World(*world_args)


def _pool_eval(states):
    return [strict_native_index(_POOL_WORLD, s) for s in states]


def native_candidates(world, state: Mapping[str, str], *, exclude_poles: bool = False,
                      exclude: Iterable[str] = (), only: Optional[Iterable[str]] = None) -> Dict[str, List[str]]:
    """Askable variables: every model variable not in the state, minus exclusions."""
    skip = set(exclude) | set(state)
    if exclude_poles:
        skip |= set(world.g.left_map) | set(world.g.right_map)
    pool = set(only) if only is not None else set(world.ctx.idx_map)
    return {v: list(world.ctx.possible[v]) for v in sorted(pool)
            if v in world.ctx.idx_map and v not in skip and world.ctx.possible.get(v)}


def native_one_step(world, state: Mapping[str, str], *, exclude_poles: bool = False,
                    exclude: Iterable[str] = (), only: Optional[Iterable[str]] = None,
                    workers: int = 1, world_args: Optional[Tuple[str, str, str, str]] = None,
                    fast: Optional[bool] = None) -> OneStepResult:
    """One-step geometry for a DTAG :class:`optimizer.dtag_bridge.World`.

    ``state`` is validated against the model (invalid assignments raise).

    ``fast`` (default: whenever the native binding supports it) evaluates all (item, response)
    pairs in one incremental native call: identical results, typically 10-100x faster. Otherwise
    each extended state is evaluated separately; ``workers > 1`` then needs ``world_args`` =
    (model_path, map_path, poles_path, assets_dir) to rebuild the World in each process.
    """
    ok, dropped = world.valid(dict(state))
    if dropped:
        raise ValueError(f"Assignments not valid for this model: {dropped}")
    cands = native_candidates(world, ok, exclude_poles=exclude_poles, exclude=exclude, only=only)
    if fast is None:
        fast = has_fast_extensions(world)
    elif fast and not has_fast_extensions(world):
        raise RuntimeError("Native binding lacks extension_distances; rebuild: bash scripts/build_native_bindings.sh")
    pool = None
    if workers > 1 and not fast:
        if world_args is None:
            raise ValueError("workers > 1 requires world_args")
        pool = ProcessPoolExecutor(workers, initializer=_pool_init, initargs=(tuple(world_args),))

    def index_fn(states):
        if pool is None or len(states) < 2 * workers:
            return [strict_native_index(world, s) for s in states]
        n = workers * 8
        chunks = [states[i::n] for i in range(n)]
        parts = list(pool.map(_pool_eval, chunks))
        out = [0.0] * len(states)
        for i, part in enumerate(parts):
            out[i::n] = part
        return out

    t0 = time.time()
    try:
        res = one_step_geometry(ok, cands, index_fn, lambda s, vs: native_distributions(world, s, vs),
                                I_empty=strict_native_index(world, {}), text=world.text,
                                pole_items=set(world.g.left_map) | set(world.g.right_map),
                                extension_fn=(lambda s, ps: native_extension_indices(world, s, ps)) if fast else None)
    finally:
        if pool is not None:
            pool.shutdown()
    res.meta.update({"state": ok, "exclude_poles": exclude_poles, "workers": workers, "fast": fast,
                     "seconds": time.time() - t0, "poles": world.poles_summary(),
                     "model_path": world.model_path, "map_path": world.map_path})
    return res


# --------------------------------------------------------------------------- multi-step policy runs

def policy_run(world, state: Mapping[str, str], direction: str, steps: int, rng, *,
               policy: str = "greedy_mu", exclude_poles: bool = True, exclude: Iterable[str] = (),
               only: Optional[Iterable[str]] = None,
               on_step: Optional[Callable[[Dict[str, Any]], None]] = None,
               n_alternatives: int = 5) -> List[Dict[str, Any]]:
    """One sampled trajectory s_0 -> ... -> s_T under the native model.

    At each step the policy picks a question; the ANSWER is drawn from the native
    P(a | s_t, v) (the asker never chooses it); the state is updated; repeat.

    policy='greedy_mu' -- re-enumerate all candidates exactly at s_t, ask argmax mu
                          (direction='right') or argmin mu (direction='left').
    policy='random'    -- ask a uniformly random candidate (baseline; direction ignored).

    ``rng`` is a numpy Generator. Returns one record per step (question, its mu/P_up/P_down
    at the time it was asked, drawn answer, its probability, realized Delta, J after).
    ``on_step`` (optional) is called with each step record as soon as it is computed. Each record
    also carries ``detail`` (not a flat field): J_before, every answer of the asked question with
    P and Delta (Delta only for the drawn answer under 'random'), and for 'greedy_mu' the top
    ``n_alternatives`` candidates in the push direction.
    """
    if direction not in ("right", "left"):
        raise ValueError("direction must be 'right' or 'left'")
    s, _ = world.valid(dict(state))
    I_empty = strict_native_index(world, {})
    I_t = strict_native_index(world, s)
    out = []
    for t in range(1, steps + 1):
        if policy == "greedy_mu":
            res = native_one_step(world, s, exclude_poles=exclude_poles, exclude=exclude, only=only)
            if not res.summary:
                break
            pick = res.extremes["argmax_mu" if direction == "right" else "argmin_mu"]
            v = pick["variable"]
            stats = next(r for r in res.summary if r["variable"] == v)
            rows = [r for r in res.rows if r["variable"] == v]
            labels = [r["answer"] for r in rows]
            p = [r["conditional_probability"] for r in rows]
            I_by = {r["answer"]: r["I_after"] for r in rows}
            alts = res.top("expected_delta", n_alternatives, reverse=direction == "right")
            detail = {"answers": [{"answer": r["answer"], "p": r["conditional_probability"],
                                   "delta": r["delta_I"]} for r in rows],
                      "alternatives": [{k: x[k] for k in ("variable", "expected_delta", "P_up", "P_down",
                                                          "one_sided", "range")} for x in alts],
                      "n_candidates": len(res.summary)}
        elif policy == "random":
            cands = native_candidates(world, s, exclude_poles=exclude_poles, exclude=exclude, only=only)
            if not cands:
                break
            v = sorted(cands)[int(rng.integers(len(cands)))]
            labels = cands[v]
            d = native_distributions(world, s, [v])[v]
            z = sum(d.get(a, 0.0) for a in labels)
            p = [d.get(a, 0.0) / z for a in labels]
            stats, I_by = {}, None
            detail = {"answers": [{"answer": a_, "p": p_, "delta": None} for a_, p_ in zip(labels, p)],
                      "alternatives": [], "n_candidates": len(cands)}
        else:
            raise ValueError(f"unknown policy {policy!r}")
        k = int(rng.choice(len(labels), p=[x / sum(p) for x in p]))
        a = labels[k]
        s = {**s, v: a}
        I_new = I_by[a] if I_by is not None else strict_native_index(world, s)
        detail["J_before"] = I_t - I_empty
        out.append({"step": t, "variable": v, "question_text": world.text.get(v, ""), "answer": a,
                    "p_answer": p[k], "expected_delta": stats.get("expected_delta"),
                    "P_up": stats.get("P_up"), "P_down": stats.get("P_down"),
                    "one_sided": stats.get("one_sided"), "delta_I": I_new - I_t,
                    "I_after": I_new, "J_after": I_new - I_empty, "detail": detail})
        if on_step is not None:
            on_step(out[-1])
        I_t = I_new
    return out


# --------------------------------------------------------------------------- CLI

def write_outputs(res: OneStepResult, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows, fields in (("response_level.csv", res.rows, ROW_FIELDS),
                               ("variable_summary.csv", res.summary, SUMMARY_FIELDS)):
        with (out / name).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    (out / "extremes.json").write_text(json.dumps(
        {"I_before": res.I_before, "J_before": res.J_before, "I_empty": res.I_empty,
         "extremes": res.extremes, "meta": res.meta}, indent=2, default=str))


def format_extremes(res: OneStepResult, k: int = 10) -> str:
    def line(r, cols):
        return "  " + "  ".join(f"{c}={r[c]:+.5f}" if isinstance(r[c], float) else f"{c}={r[c]}" for c in cols)
    J = "" if res.J_before is None else f"  J(s)={res.J_before:+.5f}"
    lines = [f"I(s)={res.I_before:+.5f}{J}  variables={res.meta.get('n_variables')}  "
             f"pairs={res.meta.get('n_pairs')}"]
    cols = ["variable", "expected_delta", "sd", "P_up", "P_down", "one_sided"]
    for title, key, rev in (("argmax mu (push right in expectation)", "expected_delta", True),
                            ("argmin mu (push left in expectation)", "expected_delta", False)):
        lines.append(f"-- {title}")
        lines += [line(r, cols) for r in res.top(key, k, reverse=rev)]
    lines.append("-- argmax Delta (largest right move: question, answer, probability)")
    lines += [line(r, ["variable", "answer_plus", "delta_plus", "p_answer_plus"]) for r in res.top("delta_plus", k)]
    lines.append("-- argmin Delta (largest left move)")
    lines += [line(r, ["variable", "answer_minus", "delta_minus", "p_answer_minus"])
              for r in res.top("delta_minus", k, reverse=False)]
    return "\n".join(lines)


def _parse_state(items: Sequence[str]) -> State:
    out = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--state expects variable=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv=None) -> OneStepResult:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from optimizer.dtag_bridge import DEFAULT_POLES, World, canonical_map, ensure_model

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="gss/gss_2018", help="model key, e.g. gss/gss_2018")
    ap.add_argument("--model-root", default=None, help="model cache root (default DTAG cache)")
    ap.add_argument("--map", default=None, help="semantic map CSV (default: canonical for the model)")
    ap.add_argument("--poles", default=str(DEFAULT_POLES),
                    help="pole CSV (the canonical file resolves to the model's wave-specific poles)")
    ap.add_argument("--state", action="append", default=[], help="known answer variable=value (repeatable)")
    ap.add_argument("--state-json", type=Path, help="JSON object {variable: value} of known answers")
    ap.add_argument("--persona-ref", choices=["CM", "WF"],
                    help="start from assets/question_sets/personas/target_states.json (invalid labels dropped)")
    ap.add_argument("--exclude-poles", action="store_true", help="do not consider the pole-defining items")
    ap.add_argument("--exclude", nargs="*", default=[], help="variables never to ask")
    ap.add_argument("--only", type=Path, help="text file of candidate variables (one per line)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--assets-dir", default=str(repo / "outputs" / "native_cache"))
    ap.add_argument("--out", type=Path, help="write response_level.csv, variable_summary.csv, extremes.json")
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args(argv)

    model = ensure_model(a.model, a.model_root, download=not a.no_download)
    world_args = (str(model), str(a.map or canonical_map(a.model)), str(a.poles), a.assets_dir)
    world = World(*world_args)
    state: State = {}
    if a.persona_ref:
        ref = json.loads((repo / "assets/question_sets/personas/target_states.json").read_text())
        state, dropped = world.valid(ref[a.persona_ref]["state"])
        if dropped:
            print(f"dropped (invalid for {a.model}): {dropped}", file=sys.stderr)
    if a.state_json:
        state.update(json.loads(a.state_json.read_text()))
    state.update(_parse_state(a.state))
    only = [l.strip() for l in a.only.read_text().splitlines() if l.strip()] if a.only else None
    res = native_one_step(world, state, exclude_poles=a.exclude_poles, exclude=a.exclude, only=only,
                          workers=a.workers, world_args=world_args)
    print(format_extremes(res, a.top))
    if a.out:
        write_outputs(res, a.out)
    return res


if __name__ == "__main__":
    main()
