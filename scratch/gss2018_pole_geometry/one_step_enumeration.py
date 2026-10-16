#!/usr/bin/env python3
"""Exact one-step survey-item response geometry under the native GSS 2018 LSM.

For a fixed persona state s and EVERY unassigned model variable v and EVERY
valid categorical answer a of v, compute

    Delta_v(a | s) = I(s u {v=a}) - I(s) = J(s u {v=a}) - J(s),
    J(s) = I(s) - I(empty),

together with the native conditional probability P(a | s, v).

Exhaustive reference implementation: no pruning, no sampling, no LLM.
The original 38-item GSS 2018 poles are used unchanged (the canonical pole
file resolves to assets/polar_vectors/gss/gss_2018_polar_vectors.csv).

    python scratch/gss2018_pole_geometry/one_step_enumeration.py --persona CM
    python scratch/gss2018_pole_geometry/one_step_enumeration.py --persona WF --workers 4

By default personas are the committed rich reference states
(assets/question_sets/personas/target_states.json, filtered by the 2018 model).
--personas-json accepts the LLM-decoded library cache
(outputs/optimizer/.../cache/gss_2018_base_personas.json) instead.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit import get_states  # noqa: E402
from optimizer.dtag_bridge import (  # noqa: E402
    DEFAULT_POLES, World, canonical_map, ensure_model, model_record, sha256)

import pipeline as core  # noqa: E402  (on sys.path via dtag_bridge)
from optimizer.one_step_geometry import state_row  # noqa: E402  (no U100 label truncation)

MODEL_KEY = "gss/gss_2018"
CORE = ("polviews", "partyid")
EXPECTED_I0 = 0.0600465  # handoff value, checked to 1e-6
ROW_FIELDS = ["variable", "question_text", "answer", "answer_index", "conditional_probability",
              "is_pole_item", "pole_L", "pole_R", "I_before", "I_after", "J_before", "J_after",
              "delta_I", "delta_J", "d_L_after", "d_R_after"]
SUMMARY_FIELDS = ["variable", "question_text", "is_pole_item", "n_answers", "n_answers_p_positive",
                  "delta_plus", "answer_plus", "p_answer_plus", "delta_minus", "answer_minus",
                  "p_answer_minus", "range", "expected_delta", "variance", "sd",
                  "modal_answer", "p_modal", "delta_modal", "entropy_bits", "raw_prob_sum",
                  "offsupport_mass"]

_W = None  # per-process World


def _init_worker(world_args):
    global _W
    _W = World(*world_args)


def native_index(world, state):
    """I(s) with explicit distances; fails instead of World.I's silent 0.0 on nonfinite values."""
    m, g = world.m, world.g
    x = state_row(world, state)
    if hasattr(m, "distances_to_state"):
        dl, dr = m.distances_to_state(g.sL, g.sR, x)
    else:
        dl, dr = m.qdistance(g.sL, x), m.qdistance(g.sR, x)
    dl, dr = float(dl), float(dr)
    if not (math.isfinite(dl) and math.isfinite(dr) and math.isfinite(g.dLR) and g.dLR > 0):
        raise FloatingPointError(f"Nonfinite native distance for state {state}")
    return (dl - dr) / float(g.dLR), dl, dr


def _eval_pairs(base_state, pairs):
    out = []
    for v, a in pairs:
        s = dict(base_state)
        s[v] = a
        out.append((v, a) + native_index(_W, s))
    return out


def raw_distributions(world, state, variables):
    """Unfiltered native P(. | s, v) plus support audit (World.dists renormalizes silently)."""
    raw = core.qnet_conditional_distributions(world.m, state_row(world, state), target_vars=list(variables))
    out, audit = {}, {}
    for v in variables:
        d = {str(k): float(p) for k, p in (raw.get(v) or {}).items()}
        support = world.ctx.possible.get(v, [])
        total = sum(d.values())
        off = sum(p for k, p in d.items() if k not in support)
        on = {a: d.get(a, 0.0) for a in support}
        s_on = sum(on.values())
        out[v] = {a: (p / s_on if s_on > 0 else float("nan")) for a, p in on.items()}
        audit[v] = {"raw_sum": total, "offsupport_mass": off,
                    "offsupport_labels": sorted(k for k in d if k not in support)}
    return out, audit


def load_persona(world, args):
    if args.personas_json:
        entries = json.loads(Path(args.personas_json).read_text(encoding="utf-8"))
        match = [e for e in entries if e["id"].lower().startswith(args.persona.lower())]
        if len(match) != 1:
            raise SystemExit(f"Expected one entry starting with {args.persona!r} in {args.personas_json}")
        state, dropped = world.valid(match[0]["state"])
        source = f"{args.personas_json}#{match[0]['id']}"
    else:
        states, rejected = get_states(world)
        state = states[f"{args.persona}_rich"]
        dropped = [r["assignment"] for r in rejected if r["persona"] == args.persona]
        source = "assets/question_sets/personas/target_states.json (rich, 2018-valid subset)"
    missing = [k for k in CORE if k not in state]
    if missing:
        raise SystemExit(f"Persona lacks protected anchors {missing}")
    return state, dropped, source


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def summarize(variable, rows, world, audit):
    p = np.array([r["conditional_probability"] for r in rows], dtype=float)
    d = np.array([r["delta_I"] for r in rows], dtype=float)
    imax, imin, imod = int(np.argmax(d)), int(np.argmin(d)), int(np.argmax(p))
    mu = float(np.dot(p, d))
    var = float(np.dot(p, (d - mu) ** 2))
    nz = p[p > 0]
    return {"variable": variable, "question_text": world.text.get(variable, ""),
            "is_pole_item": variable in world.g.left_map, "n_answers": len(rows),
            "n_answers_p_positive": int((p > 0).sum()),
            "delta_plus": float(d[imax]), "answer_plus": rows[imax]["answer"], "p_answer_plus": float(p[imax]),
            "delta_minus": float(d[imin]), "answer_minus": rows[imin]["answer"], "p_answer_minus": float(p[imin]),
            "range": float(d[imax] - d[imin]), "expected_delta": mu, "variance": var, "sd": math.sqrt(var),
            "modal_answer": rows[imod]["answer"], "p_modal": float(p[imod]), "delta_modal": float(d[imod]),
            "entropy_bits": float(-(nz * np.log2(nz)).sum()),
            "raw_prob_sum": audit["raw_sum"], "offsupport_mass": audit["offsupport_mass"]}


def run(args):
    out = (args.out / args.persona).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    model = ensure_model(MODEL_KEY, None, download=not args.no_download)
    map_path = canonical_map(MODEL_KEY)
    world_args = (str(model), str(map_path), str(DEFAULT_POLES), str(args.out / "native_cache"))
    world = World(*world_args)
    t0 = time.time()

    I_empty, _, _ = native_index(world, {})
    state, dropped, source = load_persona(world, args)
    I_before, dL0, dR0 = native_index(world, state)
    J_before = I_before - I_empty
    if not math.isclose(I_before, world.I(state), rel_tol=0, abs_tol=1e-12):
        raise AssertionError("native_index disagrees with World.I")

    eligible = sorted(v for v in world.ctx.idx_map if v not in state and world.ctx.possible.get(v))
    pairs = [(v, a) for v in eligible for a in world.ctx.possible[v]]
    probs, paudit = raw_distributions(world, state, eligible)
    print(f"[{args.persona}] I(empty)={I_empty:+.7f} I(s)={I_before:+.7f} J(s)={J_before:+.7f} "
          f"|s|={len(state)} eligible={len(eligible)} pairs={len(pairs)} workers={args.workers}", flush=True)

    t1 = time.time()
    if args.workers <= 1:
        _init_worker(world_args)
        results = _eval_pairs(state, pairs)
    else:
        chunks = [pairs[i::args.workers * 8] for i in range(args.workers * 8)]
        with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(world_args,)) as ex:
            results = [r for part in ex.map(_eval_pairs, [state] * len(chunks), chunks) for r in part]
    t_enum = time.time() - t1
    by_pair = {(v, a): (I, dl, dr) for v, a, I, dl, dr in results}
    if len(by_pair) != len(pairs):
        raise AssertionError("Missing or duplicated (variable, answer) evaluations")

    rows, summary = [], []
    for v in eligible:
        vrows = []
        for k, a in enumerate(world.ctx.possible[v]):
            I_after, dl, dr = by_pair[(v, a)]
            J_after = I_after - I_empty
            vrows.append({"variable": v, "question_text": world.text.get(v, ""), "answer": a,
                          "answer_index": k, "conditional_probability": probs[v][a],
                          "is_pole_item": v in world.g.left_map, "pole_L": world.g.left_map.get(v, ""),
                          "pole_R": world.g.right_map.get(v, ""), "I_before": I_before, "I_after": I_after,
                          "J_before": J_before, "J_after": J_after, "delta_I": I_after - I_before,
                          "delta_J": J_after - J_before, "d_L_after": dl, "d_R_after": dr})
        rows += vrows
        summary.append(summarize(v, vrows, world, paudit[v]))

    # ---------------- validation
    rng = random.Random(args.seed)
    redo = rng.sample(pairs, min(args.recheck, len(pairs)))
    repeat = _eval_pairs(state, redo) if _W is not None else None
    if repeat is None:
        _init_worker(world_args)
        repeat = _eval_pairs(state, redo)
    det_maxdiff = max(abs(I - by_pair[(v, a)][0]) for v, a, I, _, _ in repeat)
    psums = [sum(probs[v].values()) for v in eligible]
    dIJ = max(abs(r["delta_I"] - r["delta_J"]) for r in rows)
    pzero = [v for v in eligible if not any(probs[v][a] > 0 for a in probs[v])]
    validation = {
        "all_answers_valid": all(a in world.ctx.possible[v] for v, a in pairs)
                             and all(world.valid({v: a})[0] == {v: a} for v, a in pairs),
        "persona_state_valid": world.valid(state)[0] == state,
        "empty_offset": I_empty, "empty_offset_matches_handoff": abs(I_empty - EXPECTED_I0) < 1e-6,
        "max_abs_delta_I_minus_delta_J": dIJ,
        "determinism_rechecked_pairs": len(redo), "determinism_max_abs_diff": det_maxdiff,
        "prob_sum_on_support_min": min(psums), "prob_sum_on_support_max": max(psums),
        "raw_prob_sum_min": min(a["raw_sum"] for a in paudit.values()),
        "raw_prob_sum_max": max(a["raw_sum"] for a in paudit.values()),
        "max_offsupport_mass": max(a["offsupport_mass"] for a in paudit.values()),
        "variables_with_offsupport_labels": {v: a["offsupport_labels"] for v, a in paudit.items()
                                             if a["offsupport_labels"]},
        "variables_with_no_positive_probability": pzero,
        "expected_delta_identity_max_abs_err": None,
    }
    # E[Delta] identity: sum_a P(a) I(s_{v,a}) - I(s) == mu_v
    errs = [abs(sum(probs[r0["variable"]][r["answer"]] * r["I_after"] for r in rows if r["variable"] == r0["variable"])
                - I_before - r0["expected_delta"]) for r0 in summary[:50]]
    validation["expected_delta_identity_max_abs_err"] = max(errs)

    write_csv(out / "response_level.csv", rows, ROW_FIELDS)
    summary.sort(key=lambda r: -r["range"])
    write_csv(out / "variable_summary.csv", summary, SUMMARY_FIELDS)

    nonpole = [r for r in summary if not r["is_pole_item"]]
    meta = {
        "persona": args.persona, "persona_source": source, "state": state, "dropped_assignments": dropped,
        "I_empty": I_empty, "I_before": I_before, "J_before": J_before, "d_L_before": dL0, "d_R_before": dR0,
        "d_LR": float(world.g.dLR), "n_eligible_variables": len(eligible), "n_pairs": len(pairs),
        "n_pole_items_eligible": sum(r["is_pole_item"] for r in summary),
        "eligibility": "every model variable not already assigned in s with >=1 valid label; pole items "
                       "included and flagged (is_pole_item)",
        "seconds_enumeration": t_enum, "seconds_total": time.time() - t0,
        "seconds_per_pair": t_enum / len(pairs), "workers": args.workers,
        "model": {"key": MODEL_KEY, "path": str(model), "record": model_record(MODEL_KEY)},
        "map": {"path": str(Path(map_path).relative_to(ROOT)) if str(map_path).startswith(str(ROOT)) else str(map_path),
                "sha256": sha256(Path(map_path))},
        "poles": world.poles_summary(), "poles_dropped": world.g.dropped,
        "native_runtime_sha256": next((sha256(p) for p in (ROOT / "native/lsm_runtime/python").glob("dtag_lsm*.so")), None),
        "python": platform.python_version(), "numpy": np.__version__,
        "validation": validation,
        "headline": {
            "sum_abs_expected_delta_all": float(sum(abs(r["expected_delta"]) for r in summary)),
            "max_range_nonpole": max((r["range"] for r in nonpole), default=None),
            "max_range_pole": max((r["range"] for r in summary if r["is_pole_item"]), default=None),
        },
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    print(json.dumps({k: meta[k] for k in ("persona", "J_before", "n_pairs", "seconds_enumeration")}), flush=True)
    print(json.dumps(validation, indent=2, default=str)[:3000], flush=True)
    return meta


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--persona", choices=["CM", "WF"], required=True)
    p.add_argument("--personas-json", type=Path, default=None)
    p.add_argument("--workers", type=int, default=1, help="1 = serial reference")
    p.add_argument("--recheck", type=int, default=300, help="pairs re-evaluated for determinism")
    p.add_argument("--seed", type=int, default=2018)
    p.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "one_step_enumeration")
    p.add_argument("--no-download", action="store_true")
    run(p.parse_args(argv))


if __name__ == "__main__":
    main()
