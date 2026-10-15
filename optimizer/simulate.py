"""Parallel native simulation.

A question is answered like a DTAG session answers it: the conditional distributions of all its
survey variables are computed from the current state, each answer is drawn (``draw``) or taken
as the most likely (``max``), all answers are written into the state, and the ideology index is
recomputed. Sequences are path dependent: every answer conditions the next question.
"""
from __future__ import annotations

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
    CFG = cfg


def _start(args) -> Tuple[Dict[str, str], float]:
    state, seed = args
    st = perturb(W, state, random.Random(seed), CFG["drop"], CFG["resample"], CFG["core"]) if seed is not None else dict(state)
    return st, W.I(st)


def answer(world: World, state: Dict[str, str], variables: Sequence[str], mode: str, rng: random.Random) -> Dict[str, str]:
    dists = world.dists(state, [v for v in variables if v in world.ctx.idx_map])
    new = dict(state)
    for v, d in dists.items():
        if mode == "max":
            new[v] = max(d, key=d.get)
        else:
            new[v] = rng.choices(list(d), weights=list(d.values()))[0]
    return new


def _run(args) -> List[float]:
    state, i_start, seq, mode, seed, traj = args
    rng = random.Random(seed)
    out = [i_start]
    st = dict(state)
    for variables in seq:
        st = answer(W, st, variables, mode, rng)
        if traj:
            out.append(W.I(st))
    if not traj:
        out.append(W.I(st) if seq else i_start)
    return out


class Simulator:
    """Owns the worker pool. ``runs`` are (participant_index, start_state, I_start, draw_seed)."""

    def __init__(self, world_args: Tuple[str, str, str, str], perturb_cfg: Dict[str, Any], workers: Optional[int] = None):
        n = workers or max(1, (os.cpu_count() or 2))
        self.pool = mp.get_context("fork").Pool(n, initializer=_init, initargs=(world_args, perturb_cfg))
        self.workers = n

    def close(self) -> None:
        self.pool.close()
        self.pool.join()

    def make_runs(self, participants: List[Dict[str, Any]], reps: int, seed0: int, perturb_on: bool = True,
                  only_directed: bool = True) -> List[Tuple[int, Dict[str, str], float, int]]:
        """``reps`` perturbed starts per participant. Seeds are derived from ``seed0`` so blocks
        with different ``seed0`` are disjoint and every candidate is scored on the same runs."""
        idx = [i for i, p in enumerate(participants) if p["direction"] != 0 or not only_directed]
        jobs, meta = [], []
        for i in idx:
            for r in range(reps):
                s = seed0 * 1_000_003 + i * 10_007 + r
                jobs.append((participants[i]["state"], s if perturb_on else None))
                meta.append((i, s * 7 + 3))
        starts = self.pool.map(_start, jobs, chunksize=max(1, len(jobs) // (self.workers * 4) or 1))
        return [(i, st, i0, dseed) for (i, dseed), (st, i0) in zip(meta, starts)]

    def simulate(self, runs, seq_vars: List[List[str]], mode: str, trajectories: bool = False) -> List[List[float]]:
        jobs = [(st, i0, seq_vars, mode, dseed, trajectories) for _, st, i0, dseed in runs]
        return self.pool.map(_run, jobs, chunksize=max(1, len(jobs) // (self.workers * 4) or 1))
