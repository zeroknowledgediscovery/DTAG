#!/usr/bin/env python3
"""Read-only full-native numerical parity: V3 vs the actual webapp.

No participant answers, no OpenAI calls, no writes to GCS/Firestore. Requires
the same installed native LSM model/bindings that Cloud Run uses. This
complements synthetic pytest; it does not validate free-text LLM semantics.
"""
from __future__ import annotations

import argparse
import math
import threading
from pathlib import Path
from types import SimpleNamespace

from human_study.adapter import NativeAdapter
from human_study.policy import choose_next_item, initial_rng
from human_study.state import HumanDTAGState
from human_study.study_config import StudyConfig


def check_close(name, actual, expected):
    if not math.isclose(float(actual), float(expected), rel_tol=1e-7, abs_tol=1e-8):
        raise AssertionError(f"{name}: {actual!r} != {expected!r}")


def audit(config, adapter):
    from dtag_engine import POLAR_VECTOR_SETS
    from optimizer.session_push import askable_items, suggest

    if config.candidate_mode != "native_webapp" or config.push_response_mode != "draw":
        raise ValueError("requires native_webapp + draw, not instrument-limited mode")
    expected_poles = Path(adapter.world.g.path).resolve()
    webapp_poles = Path(__file__).resolve().parents[2] / POLAR_VECTOR_SETS["gss_default"]["path"]
    if expected_poles != webapp_poles.resolve():
        raise AssertionError("webapp and human study use different ideology pole files")

    observed = {}
    configurations = [dict(observed)]
    for item in config.bank("baseline"):
        observed[item.item_id] = item.choices[0].native_value
        configurations.append(dict(observed))
    for n, state in enumerate(configurations):
        if len(state) not in {0, 2, len(config.bank("baseline"))}:
            continue
        session = SimpleNamespace(
            ctx=adapter.world.ctx, polar=adapter.world.g,
            model=adapter.world.m, state=dict(state),
            ideology_enabled=True, lock=threading.RLock(),
            config=SimpleNamespace(resp_mode="draw", state_keep=500),
        )
        webapp = suggest(session, include_pole_items=False, mode="realistic")
        webapp_candidates = set(askable_items(session, include_pole_items=False))
        study_candidates = set(adapter.webapp_candidates(state, config))
        if webapp_candidates != study_candidates:
            raise AssertionError(
                f"candidate sets diverged at state {n}: webapp-only="
                f"{sorted(webapp_candidates - study_candidates)[:10]}, "
                f"study-only={sorted(study_candidates - webapp_candidates)[:10]}"
            )
        check_close(f"index at state {n}", adapter.index(state),
                    webapp["current_ideology"])
        human_state = HumanDTAGState(
            "audit", config.model_key, config.config_hash, adapter.provenance,
            state, state, (), tuple(state), (), (),
            adapter.index(state), adapter.index(state),
        )
        for direction, updown in (("right", "up"), ("left", "down")):
            expected = webapp.get(updown)
            actual = choose_next_item(
                human_state, direction, set(), initial_rng(777),
                config, adapter,
            )
            if expected is None:
                if actual["status"] != "no_candidate":
                    raise AssertionError(f"webapp has no {updown}, study picked {actual}")
            else:
                if actual["status"] != "selected":
                    raise AssertionError(f"study failed {direction} despite webapp suggestion")
                if actual["variable"] != expected["variable"]:
                    raise AssertionError(
                        f"direction {direction} at state {n}: study "
                        f"{actual['variable']} != webapp {expected['variable']}"
                    )
                check_close(f"{direction} mu at state {n}",
                            actual["expected_delta"], expected["expected_delta"])
                check_close(f"{direction} predicted delta at state {n}",
                            actual["predicted_delta"], expected["predicted_delta"])
        print(f"PASS state={n} coordinates={len(state)} "
              f"candidate_count={len(study_candidates)} "
              f"I={adapter.index(state):+.9f}, webapp=study")
    print("PASS native GSS webapp selection, draw geometry, poles and candidate parity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="human_study/config/study.v3.example.yaml",
    )
    args = parser.parse_args()
    config = StudyConfig.load(args.config)
    adapter = NativeAdapter(config)
    adapter.validate_config(config)
    audit(config, adapter)


if __name__ == "__main__":
    main()
