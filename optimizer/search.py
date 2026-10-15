"""Search for a sequence that polarizes: positive participants move up, negative ones move down.

Objective (``robust``, default): for each run, the *signed* change is direction x (I_end - I_start),
where direction = sign of the participant's starting ideology. For each group (positive, negative)
t = mean / standard error of the signed changes over its runs; the objective is the smaller of the
two t values, so a sequence only scores well if BOTH groups move outward consistently.
``mean`` uses the smaller of the two group means instead.

Steps: (1) score every bank question alone; (2) build the sequence greedily from the best
questions; (3) refine by local search (replace a question or swap two positions, keep if better);
(4) choose the length (between ``min_length`` and ``length``) on the search runs. Every candidate
is scored on the same simulated runs (common random numbers); validation uses different runs.
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np


def group_stats(participants: List[Dict[str, Any]], runs, finals: Sequence[Sequence[float]], k: int = -1) -> Dict[str, Any]:
    """Signed change after k questions (default: all), per group."""
    out: Dict[str, Any] = {}
    for g, name in ((1, "positive"), (-1, "negative")):
        x = np.array([g * (f[k] - f[0]) for (i, _, _, _), f in zip(runs, finals) if participants[i]["direction"] == g])
        n = len(x)
        mean = float(x.mean()) if n else float("nan")
        sd = float(x.std(ddof=1)) if n > 1 else float("nan")
        se = sd / math.sqrt(n) if n > 1 else float("nan")
        out[name] = {"n": n, "mean_signed_change": mean, "sd": sd,
                     "t": mean / se if n > 1 and se > 0 else (math.inf if mean > 0 else -math.inf if mean < 0 else 0.0),
                     "share_outward": float((x > 0).mean()) if n else float("nan")}
    return out


def objective(stats: Dict[str, Any], kind: str = "robust") -> float:
    key = "t" if kind == "robust" else "mean_signed_change"
    return min(stats["positive"][key], stats["negative"][key])


class Searcher:
    def __init__(self, sim, participants, bank: List[Dict[str, Any]], mode: str, kind: str, log: Callable = print):
        self.sim, self.people, self.bank, self.mode, self.kind, self.log = sim, participants, bank, mode, kind, log
        self.by_id = {q["id"]: q for q in bank}
        self.evals = 0

    def score(self, ids: List[str], runs) -> Tuple[float, Dict[str, Any]]:
        self.evals += 1
        finals = self.sim.simulate(runs, [self.by_id[i]["variables"] for i in ids], self.mode)
        st = group_stats(self.people, runs, finals)
        return objective(st, self.kind), st

    def screen(self, runs, pool: int, per_group: int) -> Tuple[List[str], List[Dict[str, Any]]]:
        rows = []
        for n, q in enumerate(self.bank):
            obj, st = self.score([q["id"]], runs)
            rows.append({"id": q["id"], "question": q["question"], "objective": obj,
                         "t_positive": st["positive"]["t"], "t_negative": st["negative"]["t"],
                         "mean_positive": st["positive"]["mean_signed_change"],
                         "mean_negative": st["negative"]["mean_signed_change"]})
            if (n + 1) % 50 == 0:
                self.log(f"  screened {n + 1}/{len(self.bank)}")
        rows.sort(key=lambda r: -r["objective"])
        chosen = [r["id"] for r in rows[:pool]]
        for key in ("t_positive", "t_negative"):  # material for each side, even if one-sided
            for r in sorted(rows, key=lambda r: -r[key])[:per_group]:
                if r["id"] not in chosen:
                    chosen.append(r["id"])
        return chosen, rows

    def greedy(self, pool: List[str], runs, length: int) -> List[str]:
        seq: List[str] = []
        for step in range(length):
            best, best_obj = None, -math.inf
            for q in pool:
                if q in seq:
                    continue
                obj, _ = self.score(seq + [q], runs)
                if obj > best_obj:
                    best, best_obj = q, obj
            if best is None:
                break
            seq.append(best)
            self.log(f"  greedy {step + 1}/{length}: {best:14s} objective={best_obj:+.3f} | {self.by_id[best]['question'][:70]}")
        return seq

    def local_search(self, seq: List[str], pool: List[str], runs, budget: int, seed: int) -> Tuple[List[str], List[Dict]]:
        rng = random.Random(seed)
        cur = list(seq)
        best, st = self.score(cur, runs)
        history = [{"eval": 0, "move": "start", "objective": best, "sequence": list(cur)}]
        self.log(f"  local search start: objective={best:+.3f} (pos t={st['positive']['t']:+.2f}, neg t={st['negative']['t']:+.2f})")
        for e in range(1, budget + 1):
            trial = list(cur)
            if len(cur) > 1 and rng.random() < 0.3:
                a, b = rng.sample(range(len(cur)), 2)
                trial[a], trial[b] = trial[b], trial[a]
                move = f"swap {a + 1}<->{b + 1}"
            else:
                choices = [q for q in pool if q not in cur]
                if not choices:
                    continue
                pos, new = rng.randrange(len(cur)), rng.choice(choices)
                move = f"replace {pos + 1}: {cur[pos]} -> {new}"
                trial[pos] = new
            obj, st = self.score(trial, runs)
            if obj > best:
                cur, best = trial, obj
                history.append({"eval": e, "move": move, "objective": obj, "sequence": list(cur)})
                self.log(f"  eval {e}/{budget}: {move}  objective={obj:+.3f} "
                         f"(pos t={st['positive']['t']:+.2f}, neg t={st['negative']['t']:+.2f})  [accepted]")
        return cur, history

    def choose_length(self, seq: List[str], runs, min_length: int) -> Tuple[int, List[Dict[str, Any]]]:
        finals = self.sim.simulate(runs, [self.by_id[i]["variables"] for i in seq], self.mode, trajectories=True)
        rows = []
        for L in range(1, len(seq) + 1):
            st = group_stats(self.people, runs, finals, k=L)
            rows.append({"length": L, "objective": objective(st, self.kind),
                         "t_positive": st["positive"]["t"], "t_negative": st["negative"]["t"]})
        eligible = [r for r in rows if r["length"] >= min_length] or rows
        return max(eligible, key=lambda r: r["objective"])["length"], rows
