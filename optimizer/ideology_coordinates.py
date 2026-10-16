"""Read-only ideology coordinate transforms for descriptive LSM evaluation.

Native DTAG World.I remains the historical uncentered metric. These helpers
do not modify question generation, response distributions, or optimization.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

COORDINATE = "empty_centered_v1"


def empty_state_offset(world) -> float:
    """Return the index of the unconditioned state for this exact model/pole."""
    offset = float(world.I({}))
    if not np.isfinite(offset):
        raise ValueError("Nonfinite empty-state ideology index")
    return offset


def recenter_runs_and_trajectories(runs: Sequence, trajectories, offset: float):
    """Return copies with the same constant removed from EVERY index.

    Runs are (persona, initial_state, initial_I, seed, state_id).
    Changes and variances are preserved up to floating-point precision.
    """
    trajectories = np.asarray(trajectories, dtype=float)
    if trajectories.ndim != 2 or trajectories.shape[0] != len(runs):
        raise ValueError("Trajectory rows must match runs")
    if not np.isfinite(trajectories).all() or not np.isfinite(offset):
        raise ValueError("Nonfinite index values")
    centered_runs = [(r[0], r[1], float(r[2])-float(offset), r[3], r[4])
                     for r in runs]
    centered_paths = trajectories - float(offset)
    if not np.allclose(centered_paths[:, 0],
                       [r[2] for r in centered_runs], atol=1e-9):
        raise ValueError("Starting indices disagree between runs and trajectories")
    return centered_runs, centered_paths


def centered_persona_diagnostics(people, offset: float, band=0.005):
    """Descriptive starting signs, not a target for sequence selection."""
    result = []
    for person in people:
        raw = float(person["I0"])
        centered = raw-float(offset)
        label = 0 if abs(centered) < band else (1 if centered > 0 else -1)
        result.append({"persona": person["id"], "I_raw": raw,
                       "I_centered": centered, "starting_sign": label})
    return result
