"""Native DTAG simulation with immutable persona anchors and reproducible starting states."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .dtag_bridge import World
from .population import perturb

W: Optional[World] = None
CFG: Dict[str, Any] = {}


def _init(world_args: Tuple[str, str, str, str], cfg: Dict[str, Any]) -> None:
    global W, CFG
    W = World(*world_args)
    CFG = dict(cfg)
    forbidden = set(CFG.get("exclude_vars") or [])
    CFG["augment_pool"] = [
        v for v in W.ctx.feat
        if v not in forbidden and bool(W.text.get(v))
        and 2 <= len(W.ctx.possible.get(v, [])) <= 15
    ]


def _start(args) -> Tuple[Dict[str, str], float]:
    state, seed, protected, augment_count = args
    rng = random.Random(seed)
    fixed = set(protected)
    st = perturb(W, state, rng, CFG["drop"], CFG["resample"], list(fixed)) if seed is not None else dict(state)
    if augment_count:
        pool = [v for v in CFG["augment_pool"] if v not in st and v not in fixed]
        rng.shuffle(pool)
        for v in pool[:augment_count]:
            d = W.dists(st, [v]).get(v)
            if d:
                st[v] = rng.choices(list(d), weights=list(d.values()))[0]
    for k, v in protected.items():
        if st.get(k) != v:
            raise AssertionError(f"persona anchor {k} changed during initialization")
    return st, W.I(st)


def answer(world: World, state: Dict[str, str], variables: Sequence[str], mode: str,
           rng: random.Random, protected: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Answer conditional on the current state; never overwrite protected persona assignments."""
    protected = protected or {}
    targets = [v for v in variables if v in world.ctx.idx_map and v not in protected]
    dists = world.dists(state, targets) if targets else {}
    new = dict(state)
    for v, d in dists.items():
        if mode == "max":
            new[v] = max(d, key=d.get)
        else:
            new[v] = rng.choices(list(d), weights=list(d.values()))[0]
    for k, v in protected.items():
        if new.get(k) != v:
            raise AssertionError(f"persona anchor {k} changed during question answering")
    return new


def _run(args) -> List[float]:
    state, i_start, seq, mode, seed, traj, protected = args
    rng = random.Random(seed)
    out = [i_start]
    st = dict(state)
    for variables in seq:
        st = answer(W, st, variables, mode, rng, protected)
        if traj:
            out.append(W.I(st))
    if not traj:
        out.append(W.I(st) if seq else i_start)
    return out


class Simulator:
    """Run layout: (persona_index, starting_state, I_start, draw_seed, state_id)."""

    def __init__(self, world_args: Tuple[str, str, str, str], perturb_cfg: Dict[str, Any],
                 workers: Optional[int] = None):
        self.people: Optional[List[Dict[str, Any]]] = None
        n = workers or max(1, os.cpu_count() or 2)
        self.pool = mp.get_context("fork").Pool(n, initializer=_init, initargs=(world_args, perturb_cfg))
        self.workers = n

    def close(self) -> None:
        self.pool.close()
        self.pool.join()

    def make_runs(self, participants: List[Dict[str, Any]], reps: int, seed0: int,
                  perturb_on: bool = True, only_directed: bool = True,
                  states_per_persona: int = 1, augment_count: int = 0):
        """Create distinct starting states and repeated stochastic trajectories.

        For states_per_persona=1, preserve historical behavior: every repetition
        independently perturbs the persona. For states_per_persona>1, generate a fixed
        starting state per state_id and take reps independent draws from it.
        """
        if reps < 1 or states_per_persona < 1:
            raise ValueError("reps and states_per_persona must be positive")
        self.people = participants
        inds = [i for i, p in enumerate(participants) if not only_directed or p["direction"] != 0]
        jobs, meta = [], []
        if states_per_persona == 1:
            for i in inds:
                for r in range(reps):
                    s = seed0 * 1_000_003 + i * 10_007 + r
                    jobs.append((participants[i]["state"], s if perturb_on else None,
                                 participants[i].get("protected_values", {}), augment_count))
                    meta.append((i, f"{i}:r{r}", s * 7 + 3, 1))
        else:
            for i in inds:
                for j in range(states_per_persona):
                    s = seed0 * 1_000_003 + i * 10_007 + j
                    jobs.append((participants[i]["state"], s if perturb_on else None,
                                 participants[i].get("protected_values", {}), augment_count))
                    meta.append((i, f"{i}:s{j}", s * 7 + 3, reps))
        starts = self.pool.map(_start, jobs, chunksize=max(1, len(jobs) // (self.workers * 4)))
        runs = []
        for (i, state_id, seed, n_draws), (st, i0) in zip(meta, starts):
            # An independently seeded construction need not yield a DISTINCT state.
            # Hash the full state so duplicated starting assignments are one cluster.
            if states_per_persona > 1:
                digest = hashlib.sha256(json.dumps(st, sort_keys=True).encode()).hexdigest()[:20]
                state_id = f"{i}:{digest}"
            for draw in range(n_draws):
                runs.append((i, st, i0, seed + 1_000_000_007 * draw, state_id))
        return runs

    def simulate(self, runs, seq_vars: List[List[str]], mode: str,
                 trajectories: bool = False) -> List[List[float]]:
        if self.people is None:
            raise RuntimeError("make_runs must be called before simulate")
        jobs = [(r[1], r[2], seq_vars, mode, r[3], trajectories,
                 self.people[r[0]].get("protected_values", {})) for r in runs]
        return self.pool.map(_run, jobs, chunksize=max(1, len(jobs) // (self.workers * 4)))
