#!/usr/bin/env python3
"""
Search for 5-10 question DTAG intervention sequences in four directional classes:

  both_up          CM up, WF up
  both_down        CM down, WF down
  cm_up_wf_down    CM up, WF down
  cm_down_wf_up    CM down, WF up

The natural-language question bank is generated separately. During Monte Carlo
search, each question is applied through its retained source-variable mapping,
so no LLM call occurs inside the replicate loop. Native conditional response
distributions are sampled with state updates after every question.

Example:
  python applications/question_sequence_optimization/optimize_sequences.py \
      --question_bank outputs/qseq/gss2024_question_bank.jsonl \
      --outdir outputs/qseq/search01 \
      --screen_reps 80 --confirm_reps 1000 \
      --random_sequences 2500 --sets_per_category 8
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pipeline as core
from dtag_engine import DTAGEngine


CATEGORIES = {
    "both_up": (+1, +1),
    "both_down": (-1, -1),
    "cm_up_wf_down": (+1, -1),
    "cm_down_wf_up": (-1, +1),
}


def read_bank(path: str) -> List[Dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                r["source_variables"] = [str(v).strip().lower() for v in r.get("source_variables", [])]
                if r.get("question") and r["source_variables"]:
                    rows.append(r)
    if not rows:
        raise ValueError("question bank is empty")
    return rows


def bootstrap_ci(x: Sequence[float], level: float, nboot: int, rng: np.random.Generator) -> Tuple[float, float]:
    a = np.asarray(x, dtype=float)
    if len(a) == 0:
        return (math.nan, math.nan)
    if len(a) == 1 or nboot <= 0:
        return (float(a.mean()), float(a.mean()))
    idx = rng.integers(0, len(a), size=(nboot, len(a)))
    means = a[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    return (float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha)))


def wilson_ci(k: int, n: int, level: float = 0.95) -> Tuple[float, float]:
    if n <= 0:
        return (math.nan, math.nan)
    # z=1.95996 for 95%; use stdlib NormalDist for other confidence levels.
    from statistics import NormalDist
    z = NormalDist().inv_cdf(0.5 + level / 2.0)
    p = k / n
    den = 1.0 + z*z/n
    ctr = (p + z*z/(2*n)) / den
    rad = z * math.sqrt((p*(1-p) + z*z/(4*n))/n) / den
    return max(0.0, ctr-rad), min(1.0, ctr+rad)


def category_hit(cm: float, wf: float, signs: Tuple[int, int], floor: float) -> bool:
    return signs[0]*cm > floor and signs[1]*wf > floor


def robust_direction(ci: Tuple[float, float], sign: int, floor: float) -> bool:
    return ci[0] > floor if sign > 0 else ci[1] < -floor


def apply_question(sess, q: Dict, query_idx: int, seed: int) -> Dict:
    """Apply one pre-mapped natural-language question with native stochastic draw."""
    vars_ = [v for v in q["source_variables"] if v in sess.ctx.idx_map]
    if not vars_:
        return {"ideology": sess._ideology_now(), "updates": {}, "variables": []}

    null = core.build_NULL_with_assignments(sess.model, dict(sess.state), sess.ctx.idx_map)
    dists = core.qnet_conditional_distributions(sess.model, null, target_vars=vars_)
    vars_ = [v for v in vars_ if v in dists]
    if not vars_:
        return {"ideology": sess._ideology_now(), "updates": {}, "variables": []}

    resp, _ = core.responses_for_vars_from_distributions(
        dists=dists,
        var_set=vars_,
        mode="draw",
        seed=int(seed + 1009*query_idx),
    )
    updates = {}
    for v in vars_:
        val = resp.get(v)
        if val in sess.ctx.possible.get(v, []):
            if v in sess.state:
                sess.state.move_to_end(v)
            sess.state[v] = val
            updates[v] = val
    sess._evict_to_limit()
    ideol = sess._compute_and_record_ideology(query_idx)
    return {"ideology": ideol, "updates": updates, "variables": vars_}


def run_sequence(sess, seq: Sequence[Dict], seed: int) -> Tuple[float, List[float]]:
    sess.reset()
    initial = float(sess.ideology0)
    path = [initial]
    for i, q in enumerate(seq, 1):
        r = apply_question(sess, q, i, seed)
        path.append(float(r["ideology"]))
    return path[-1] - initial, path


def evaluate_pair(cm_sess, wf_sess, seq: Sequence[Dict], seeds: Sequence[int],
                  level: float, nboot: int, effect_floor: float,
                  signs: Tuple[int, int], bootstrap_seed: int) -> Dict:
    cm, wf = [], []
    for seed in seeds:
        dcm, _ = run_sequence(cm_sess, seq, int(seed))
        dwf, _ = run_sequence(wf_sess, seq, int(seed) + 7919)
        cm.append(dcm)
        wf.append(dwf)

    rng = np.random.default_rng(bootstrap_seed)
    cm_ci = bootstrap_ci(cm, level, nboot, rng)
    wf_ci = bootstrap_ci(wf, level, nboot, rng)
    hits = sum(category_hit(a, b, signs, effect_floor) for a, b in zip(cm, wf))
    p_lo, p_hi = wilson_ci(hits, len(cm), level)

    signed_cm = signs[0] * float(np.mean(cm))
    signed_wf = signs[1] * float(np.mean(wf))
    robust = robust_direction(cm_ci, signs[0], effect_floor) and robust_direction(wf_ci, signs[1], effect_floor)
    return {
        "n": len(cm),
        "cm_mean": float(np.mean(cm)),
        "cm_sd": float(np.std(cm, ddof=1)) if len(cm) > 1 else 0.0,
        "cm_ci_lo": cm_ci[0], "cm_ci_hi": cm_ci[1],
        "wf_mean": float(np.mean(wf)),
        "wf_sd": float(np.std(wf, ddof=1)) if len(wf) > 1 else 0.0,
        "wf_ci_lo": wf_ci[0], "wf_ci_hi": wf_ci[1],
        "quadrant_hits": hits,
        "quadrant_p": hits / len(cm),
        "quadrant_ci_lo": p_lo, "quadrant_ci_hi": p_hi,
        "robust": bool(robust),
        # favor balanced effects and reliable quadrant occupancy
        "score": min(signed_cm, signed_wf) + 0.25*(signed_cm + signed_wf) + 0.02*p_lo,
    }


def source_set(seq: Sequence[Dict]) -> set:
    s = set()
    for q in seq:
        s.update(q["source_variables"])
    return s


def compatible(seq: Sequence[Dict], q: Dict, allow_overlap: bool) -> bool:
    if allow_overlap:
        return q["id"] not in {x["id"] for x in seq}
    return not (source_set(seq) & set(q["source_variables"]))


def individual_screen(cm_sess, wf_sess, bank: List[Dict], seeds: Sequence[int],
                      level: float, nboot: int, effect_floor: float) -> Dict[str, Dict[str, Dict]]:
    out = {k: {} for k in CATEGORIES}
    for i, q in enumerate(bank):
        for ci, (cat, signs) in enumerate(CATEGORIES.items()):
            res = evaluate_pair(cm_sess, wf_sess, [q], seeds, level, nboot, effect_floor,
                                signs, bootstrap_seed=100000 + 17*i + ci)
            out[cat][q["id"]] = res
        if (i+1) % 20 == 0:
            print(f"[individual] {i+1}/{len(bank)}")
    return out


def make_random_sequences(rng: random.Random, pool: List[Dict], n: int,
                          min_len: int, max_len: int, allow_overlap: bool) -> List[List[Dict]]:
    seqs, seen = [], set()
    attempts = 0
    while len(seqs) < n and attempts < n*50:
        attempts += 1
        L = rng.randint(min_len, max_len)
        order = pool[:]
        rng.shuffle(order)
        seq = []
        for q in order:
            if compatible(seq, q, allow_overlap):
                seq.append(q)
            if len(seq) >= L:
                break
        if len(seq) < min_len:
            continue
        key = tuple(q["id"] for q in seq)
        if key in seen:
            continue
        seen.add(key)
        seqs.append(seq)
    return seqs


def mutate_sequences(rng: random.Random, elites: List[List[Dict]], pool: List[Dict],
                     n_each: int, min_len: int, max_len: int, allow_overlap: bool) -> List[List[Dict]]:
    out, seen = [], set()
    for base in elites:
        for _ in range(n_each):
            seq = list(base)
            op = rng.choice(["replace", "swap", "insert", "delete"])
            if op == "swap" and len(seq) >= 2:
                a, b = rng.sample(range(len(seq)), 2)
                seq[a], seq[b] = seq[b], seq[a]
            elif op == "delete" and len(seq) > min_len:
                seq.pop(rng.randrange(len(seq)))
            elif op == "insert" and len(seq) < max_len:
                choices = [q for q in pool if compatible(seq, q, allow_overlap)]
                if choices:
                    seq.insert(rng.randrange(len(seq)+1), rng.choice(choices))
            else:
                pos = rng.randrange(len(seq))
                rest = seq[:pos] + seq[pos+1:]
                choices = [q for q in pool if compatible(rest, q, allow_overlap)]
                if choices:
                    seq[pos] = rng.choice(choices)
            key = tuple(q["id"] for q in seq)
            if min_len <= len(seq) <= max_len and key not in seen:
                seen.add(key)
                out.append(seq)
    return out


def write_csv(path: Path, rows: Iterable[Dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def diverse_top(rows: List[Dict], n: int, max_jaccard: float) -> List[Dict]:
    chosen = []
    for r in sorted(rows, key=lambda x: x["score"], reverse=True):
        s = set(r["question_ids"])
        good = True
        for c in chosen:
            t = set(c["question_ids"])
            jac = len(s & t) / max(1, len(s | t))
            if jac > max_jaccard:
                good = False
                break
        if good:
            chosen.append(r)
        if len(chosen) >= n:
            break
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question_bank", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--cm_profile", default="gss2024_cm")
    ap.add_argument("--wf_profile", default="gss2024_wf")
    ap.add_argument("--min_len", type=int, default=5)
    ap.add_argument("--max_len", type=int, default=10)
    ap.add_argument("--screen_reps", type=int, default=60)
    ap.add_argument("--confirm_reps", type=int, default=1000)
    ap.add_argument("--individual_reps", type=int, default=40)
    ap.add_argument("--pool_per_category", type=int, default=50)
    ap.add_argument("--random_sequences", type=int, default=1500)
    ap.add_argument("--elite", type=int, default=60)
    ap.add_argument("--mutations_per_elite", type=int, default=12)
    ap.add_argument("--sets_per_category", type=int, default=8)
    ap.add_argument("--effect_floor", type=float, default=0.005)
    ap.add_argument("--ci", type=float, default=0.95)
    ap.add_argument("--bootstrap", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--max_jaccard", type=float, default=0.60)
    ap.add_argument("--allow_variable_overlap", action="store_true")
    args = ap.parse_args()

    if not (5 <= args.min_len <= args.max_len <= 10):
        raise SystemExit("Require 5 <= min_len <= max_len <= 10")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    bank = read_bank(args.question_bank)

    engine = DTAGEngine()
    overrides = {
        "resp_mode": "draw",
        "semantic_resp_mode": "draw",
        "semantic_fallback": "update_state",
        "state_keep": 500,
    }
    cm_es = engine.create_session(profile=args.cm_profile, overrides=overrides)
    wf_es = engine.create_session(profile=args.wf_profile, overrides=overrides)
    cm_sess, wf_sess = cm_es.session, wf_es.session
    if not cm_sess.ideology_enabled or not wf_sess.ideology_enabled:
        raise SystemExit("Both profiles must have ideology tracking enabled")

    # Restrict to questions whose retained grounding variables exist in this model.
    feat = set(cm_sess.ctx.idx_map) & set(wf_sess.ctx.idx_map)
    bank = [q for q in bank if q["source_variables"] and all(v in feat for v in q["source_variables"])]
    if len(bank) < args.max_len:
        raise SystemExit(f"Only {len(bank)} usable mapped questions remain")

    init = {
        "cm_profile": args.cm_profile, "wf_profile": args.wf_profile,
        "cm_ideology0": cm_sess.ideology0, "wf_ideology0": wf_sess.ideology0,
        "cm_initial_state": cm_sess.initial_state(), "wf_initial_state": wf_sess.initial_state(),
        "usable_questions": len(bank),
        "arguments": vars(args),
    }
    (outdir / "initialization.json").write_text(json.dumps(init, indent=2), encoding="utf-8")

    rng = random.Random(args.seed)
    indiv_seeds = [args.seed + 100000 + i for i in range(args.individual_reps)]
    screen_seeds = [args.seed + 200000 + i for i in range(args.screen_reps)]
    confirm_seeds = [args.seed + 300000 + i for i in range(args.confirm_reps)]

    indiv = individual_screen(cm_sess, wf_sess, bank, indiv_seeds, args.ci,
                              max(300, args.bootstrap//3), args.effect_floor)
    id_to_q = {q["id"]: q for q in bank}

    all_screen, all_confirm = [], []
    selected = {}
    for ci, (cat, signs) in enumerate(CATEGORIES.items()):
        ranked_ids = sorted(indiv[cat], key=lambda qid: indiv[cat][qid]["score"], reverse=True)
        pool = [id_to_q[qid] for qid in ranked_ids[:args.pool_per_category]]
        print(f"[{cat}] pool={len(pool)}")

        candidates = make_random_sequences(rng, pool, args.random_sequences,
                                           args.min_len, args.max_len, args.allow_variable_overlap)
        screen_rows = []
        seq_map = {}
        for i, seq in enumerate(candidates):
            res = evaluate_pair(cm_sess, wf_sess, seq, screen_seeds, args.ci,
                                max(300, args.bootstrap//3), args.effect_floor, signs,
                                bootstrap_seed=args.seed + ci*1000000 + i)
            sid = f"{cat}_r{i:05d}"
            seq_map[sid] = seq
            row = {"category": cat, "sequence_id": sid, "length": len(seq),
                   "question_ids": [q["id"] for q in seq],
                   "questions": [q["question"] for q in seq], **res}
            screen_rows.append(row)
            if (i+1) % 100 == 0:
                print(f"[{cat}] random screen {i+1}/{len(candidates)}")

        elites = sorted(screen_rows, key=lambda r: r["score"], reverse=True)[:args.elite]
        elite_seqs = [seq_map[r["sequence_id"]] for r in elites]
        mutated = mutate_sequences(rng, elite_seqs, pool, args.mutations_per_elite,
                                   args.min_len, args.max_len, args.allow_variable_overlap)
        for j, seq in enumerate(mutated):
            res = evaluate_pair(cm_sess, wf_sess, seq, screen_seeds, args.ci,
                                max(300, args.bootstrap//3), args.effect_floor, signs,
                                bootstrap_seed=args.seed + ci*2000000 + j)
            sid = f"{cat}_m{j:05d}"
            seq_map[sid] = seq
            screen_rows.append({"category": cat, "sequence_id": sid, "length": len(seq),
                                "question_ids": [q["id"] for q in seq],
                                "questions": [q["question"] for q in seq], **res})

        all_screen.extend(screen_rows)
        finalists = sorted(screen_rows, key=lambda r: r["score"], reverse=True)[:max(args.elite, args.sets_per_category*4)]
        confirmed = []
        for j, row in enumerate(finalists):
            seq = seq_map[row["sequence_id"]]
            res = evaluate_pair(cm_sess, wf_sess, seq, confirm_seeds, args.ci,
                                args.bootstrap, args.effect_floor, signs,
                                bootstrap_seed=args.seed + 9000000 + ci*10000 + j)
            rr = {"category": cat, "sequence_id": row["sequence_id"], "length": len(seq),
                  "question_ids": [q["id"] for q in seq],
                  "questions": [q["question"] for q in seq], **res}
            confirmed.append(rr)
        all_confirm.extend(confirmed)

        robust_rows = [r for r in confirmed if r["robust"]]
        picks = diverse_top(robust_rows or confirmed, args.sets_per_category, args.max_jaccard)
        selected[cat] = picks

        catdir = outdir / "question_sets" / cat
        catdir.mkdir(parents=True, exist_ok=True)
        for k, r in enumerate(picks, 1):
            seq = seq_map[r["sequence_id"]]
            with (catdir / f"set_{k:02d}.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["step", "question", "question_id", "source_variables"])
                for step, q in enumerate(seq, 1):
                    w.writerow([step, q["question"], q["id"], ";".join(q["source_variables"])])

    def flatten(rows):
        out = []
        for r in rows:
            x = dict(r)
            x["question_ids"] = ";".join(r["question_ids"])
            x["questions"] = " || ".join(r["questions"])
            out.append(x)
        return out

    write_csv(outdir / "screen_results.csv", flatten(all_screen))
    write_csv(outdir / "confirmed_results.csv", flatten(all_confirm))
    (outdir / "selected_sets.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    print(f"Wrote results to {outdir}")


if __name__ == "__main__":
    main()
