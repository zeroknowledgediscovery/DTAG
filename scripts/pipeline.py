#!/usr/bin/env python3
"""
DTAG native-LSM command-line runtime (core pipeline).

This is the canonical survey-grounded respondent runtime. It supports:
1) Optional ideology tracking per iteration using polar reference vectors and qdistance.
2) Ideology time-series CSV written to logs only when ideology tracking is enabled.
3) Question-sequence CSV written to logs.
4) Autoplay mode: provide a CSV of questions and the run becomes non-interactive.

Adds the WVS/location-aware conditioning features:
5) Supports year conditioning via --year when the model exposes a compatible feature.
6) Supports forcing location context via --country and/or --continent.
7) Country/continent is encoded through O1_LONGITUDE and O2_LATITUDE when those
   variables exist in the current model.
8) Country/continent names are validated against internal dictionaries.
9) Target coordinates are snapped to the nearest allowed native-LSM support values.
10) Metadata/logging includes requested and resolved geography.

Ideology index, when --polar_vectors is provided and compatible:
  I(s) = ( d(sL, s) - d(sR, s) ) / d(sL, sR)
where d is native LSM qdistance and s is the current full state vector.
If no compatible polar-vector file is provided, the pipeline still answers questions,
runs semantic fallback, and writes records, but skips ideology scoring.

Requirements:
  pip install openai pandas numpy

Env:
  export OPENAI_API_KEY="..."

Library code lives in dtag_core.py; this module adds the command-line entry point main().
``import pipeline`` remains a transparent alias of dtag_core for every library name: reads return
dtag_core's live objects, and assignments (for example pipeline_localized replacing
build_forced_assignments) are applied to dtag_core, so every caller sees them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import Dict, Optional

import dtag_core as core
from model_backend import load_model


class _CoreAlias(types.ModuleType):
    """Make ``pipeline.<name>`` read and write ``dtag_core.<name>`` for every library name."""

    def __getattr__(self, name):
        try:
            return getattr(core, name)
        except AttributeError:
            raise AttributeError(f"module 'pipeline' has no attribute {name!r}") from None

    def __setattr__(self, name, value):
        if name in _OWN_NAMES or name.startswith("__"):
            super().__setattr__(name, value)
        else:
            setattr(core, name, value)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(dir(core)))


_OWN_NAMES = {"main", "core", "types", "_CoreAlias", "_OWN_NAMES"}


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="CSV mapping file (variable -> question text)")
    ap.add_argument("--model", "--qnet", dest="qnet", required=True, help="Native LSM model directory")
    ap.add_argument("--model_backend", choices=["auto", "native_lsm"], default="native_lsm",
                    help="Native LSM runtime backend. auto is retained as a compatibility alias.")
    ap.add_argument("--persona", required=True, help="Free-text description of an individual")

    ap.add_argument("--question", default="", help="User plain text question (ignored if --loop or --autoplay_csv)")
    ap.add_argument("--loop", action="store_true", help="Read one question per line from stdin")
    ap.add_argument("--autoplay_csv", default="", help="CSV of questions to run non-interactively in order")
    ap.add_argument("--timing", action="store_true", help="Print timing breakdown per query")

    ap.add_argument("--state_keep", type=int, default=50,
                    help="Max cumulative assignments to keep (most recent kept; prevents huge conditioning)")

    ap.add_argument("--k", type=int, default=6, help="How many variables to select for answering question")
    ap.add_argument("--prefilter", type=int, default=160, help="Candidates shown to LLM after lexical prefilter")
    ap.add_argument("--min_map_score", type=float, default=1.0,
                    help="Minimum content-word lexical score required before a survey variable is considered a candidate; use 0 to allow zero-score candidates after stopword removal")
    ap.add_argument("--semantic_fallback", choices=["off", "answer_only", "update_state"], default="answer_only",
                    help="When direct mapping fails: off=no answer, answer_only=answer from indirect semantic anchors without state update, update_state=also update state from indirect anchors")
    ap.add_argument("--semantic_k", type=int, default=6,
                    help="Maximum variables to use for indirect semantic fallback")
    ap.add_argument("--semantic_prefilter", type=int, default=80,
                    help="Embedding-retrieved candidates shown to the LLM in semantic fallback")
    ap.add_argument("--semantic_min_confidence", type=float, default=0.35,
                    help="Minimum LLM bridge confidence required for semantic fallback variables")
    ap.add_argument("--semantic_embedding_model", default="text-embedding-3-small",
                    help="OpenAI embedding model used only for semantic fallback retrieval")
    ap.add_argument("--semantic_resp_mode", choices=["max", "draw"], default="max",
                    help="Response mode for indirect semantic fallback anchors; default max avoids stochastic state drift")
    ap.add_argument("--openai_model", default="gpt-4.1-mini", help="OpenAI model for all LLM steps")

    ap.add_argument("--max_assign", type=int, default=8, help="Max persona-conditioning assignments")
    ap.add_argument("--assign_prefilter", type=int, default=140, help="How many variables to offer for persona assignment")

    ap.add_argument("--resp_mode", choices=["max", "draw"], default="max", help="Response mode per selected var")
    ap.add_argument("--seed", type=int, default=1, help="RNG seed used when resp_mode=draw")

    ap.add_argument("--assets_dir", default="./assets", help="Directory for cached assets (possible responses JSON)")
    ap.add_argument("--logs_dir", default="./logs", help="Directory for run logs and reports")
    ap.add_argument("--tag", default="run", help="Tag string to include in report/log filenames")

    ap.add_argument("--polar_vectors", default="",
                    help="Optional CSV with left/right polar reference vectors. If omitted or incompatible, ideology tracking is disabled.")
    ap.add_argument("--no_ideology", action="store_true",
                    help="Disable ideology tracking even if --polar_vectors is provided.")
    ap.add_argument("--require_polar_vectors", action="store_true",
                    help="Fail instead of disabling ideology if --polar_vectors is missing or incompatible.")

    # WVS/location-aware forcing
    ap.add_argument("--year", type=int, default=None,
                    help="Force A_YEAR in initial state when A_YEAR exists in the model")
    ap.add_argument("--country", type=str, default="",
                    help="Force country context via representative O1_LONGITUDE/O2_LATITUDE")
    ap.add_argument("--continent", type=str, default="",
                    help="Optional broader geographic prior via representative O1_LONGITUDE/O2_LATITUDE")
    ap.add_argument("--list_countries", action="store_true",
                    help="Print supported countries and exit")
    ap.add_argument("--list_continents", action="store_true",
                    help="Print supported continents and exit")

    args = ap.parse_args()

    if args.list_countries:
        print("\n".join(core.list_supported_countries()))
        return
    if args.list_continents:
        print("\n".join(core.list_supported_continents()))
        return

    # Mode selection precedence:
    # autoplay_csv > loop > single question
    mode_autoplay = bool(args.autoplay_csv.strip())
    mode_loop = bool(args.loop) and not mode_autoplay
    mode_single = (not mode_autoplay) and (not mode_loop)

    if mode_single and not args.question.strip():
        print("ERROR: Provide --question, or use --loop, or provide --autoplay_csv.", file=sys.stderr)
        sys.exit(2)

    if mode_autoplay and not os.path.exists(args.autoplay_csv):
        print(f"ERROR: --autoplay_csv not found: {args.autoplay_csv}", file=sys.stderr)
        sys.exit(2)

    assets_dir = core._ensure_dir(args.assets_dir)
    logs_dir = core._ensure_dir(args.logs_dir)
    tag = core._safe_tag(args.tag)

    persona_for_run_id = args.persona
    if args.year is not None:
        persona_for_run_id += f"\n[forced_year={args.year}]"
    if args.country:
        persona_for_run_id += f"\n[forced_country={args.country}]"
    if args.continent:
        persona_for_run_id += f"\n[forced_continent={args.continent}]"

    run_id = core.make_run_id(args.qnet, args.map, persona_for_run_id, tag)
    report_base = core.make_report_base(tag, run_id)

    log_path = str(Path(logs_dir) / f"{report_base}.log")
    meta_path = str(Path(logs_dir) / f"{report_base}.meta.json")
    final_state_path = str(Path(logs_dir) / f"{report_base}.final_state.json")

    ideology_csv_path = str(Path(logs_dir) / f"{report_base}.ideology.csv")
    questions_csv_path = str(Path(logs_dir) / f"{report_base}.questions.csv")

    log_fh = open(log_path, "w", encoding="utf-8")
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    sys.stdout = core.Tee(orig_stdout, log_fh)  # type: ignore[assignment]
    sys.stderr = core.Tee(orig_stderr, log_fh)  # type: ignore[assignment]

    try:
        # The respondent algorithm lives in dtag_session.DTAGSession so that the
        # CLI and the web application execute the same implementation.
        from dtag_session import (
            DTAGConfigError,
            DTAGSession,
            ModelContext,
            SessionConfig,
            build_polar_geometry,
            default_client_factory,
        )

        timings_init: Dict[str, float] = {}
        t0 = time.time()

        meta: Dict[str, object] = {
            "run_id": run_id,
            "tag": tag,
            "timestamp_local": core._timestamp(),
            "paths": {
                "qnet": core._abspath(args.qnet),
                "map": core._abspath(args.map),
                "assets_dir": core._abspath(assets_dir),
                "logs_dir": core._abspath(logs_dir),
                "log_path": core._abspath(log_path),
                "meta_path": core._abspath(meta_path),
                "final_state_path": core._abspath(final_state_path),
                "polar_vectors": core._abspath(args.polar_vectors) if str(args.polar_vectors or "").strip() else "",
                "ideology_csv_path": core._abspath(ideology_csv_path),
                "questions_csv_path": core._abspath(questions_csv_path),
                "autoplay_csv": core._abspath(args.autoplay_csv) if mode_autoplay else "",
            },
            "params": {
                "k": args.k,
                "prefilter": args.prefilter,
                "min_map_score": args.min_map_score,
                "semantic_fallback": args.semantic_fallback,
                "semantic_k": args.semantic_k,
                "semantic_prefilter": args.semantic_prefilter,
                "semantic_min_confidence": args.semantic_min_confidence,
                "semantic_embedding_model": args.semantic_embedding_model,
                "semantic_resp_mode": args.semantic_resp_mode,
                "openai_model": args.openai_model,
                "max_assign": args.max_assign,
                "assign_prefilter": args.assign_prefilter,
                "resp_mode": args.resp_mode,
                "seed": args.seed,
                "state_keep": args.state_keep,
                "timing": bool(args.timing),
                "loop": bool(mode_loop),
                "autoplay": bool(mode_autoplay),
                "year": args.year,
                "country": args.country,
                "continent": args.continent,
                "polar_vectors": str(args.polar_vectors or ""),
                "no_ideology": bool(args.no_ideology),
                "require_polar_vectors": bool(args.require_polar_vectors),
                "model_backend": args.model_backend,
            },
            "persona": args.persona,
        }

        # Load model once through the backend-neutral runtime adapter.
        model = load_model(args.qnet, backend=args.model_backend)
        timings_init["load_model"] = time.time() - t0
        if hasattr(model, "runtime_kind"):
            meta["native_runtime_kind"] = str(model.runtime_kind)
            print(f"INFO: native runtime = {model.runtime_kind}", file=sys.stderr)
        meta["model_backend"] = getattr(model, "backend_name", args.model_backend)

        # Load map (restricted to model features) and possible responses.
        try:
            ctx = ModelContext(model, args.qnet, args.map, assets_dir=assets_dir)
        except DTAGConfigError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        timings_init["load_map"] = ctx.timings["load_map"]

        # Optional polar vectors: needed only for ideology time-series output.
        # WVS/non-GSS answering can run with no polar vector file.
        polar = build_polar_geometry(ctx, str(args.polar_vectors or ""), no_ideology=bool(args.no_ideology))
        timings_init["load_polar_vectors"] = polar.seconds
        ideology_enabled = bool(polar.enabled)
        ideology_disable_reason = polar.disable_reason
        meta["polar_vectors_summary"] = polar.summary()
        meta["ideology_enabled"] = bool(ideology_enabled)
        meta["ideology_disable_reason"] = "" if ideology_enabled else ideology_disable_reason

        if (not ideology_enabled) and args.require_polar_vectors:
            print(f"ERROR: Ideology tracking disabled: {ideology_disable_reason}", file=sys.stderr)
            sys.exit(2)
        if not ideology_enabled:
            print(f"INFO: Ideology tracking disabled: {ideology_disable_reason}", file=sys.stderr)
        else:
            if polar.path != polar.requested_path:
                print(f"INFO: using wave-specific poles {polar.path}", file=sys.stderr)
            bad = [d for d in polar.dropped if d["reason"] != "item not in model"]
            if bad:
                print(f"WARNING: pole items dropped (answer not in model labels): "
                      f"{[(d['variable'], d['reason']) for d in bad][:10]}", file=sys.stderr)

        timings_init["possible_cache"] = ctx.timings["possible_cache"]
        meta["paths"]["possible_cache_path"] = ctx.possible_cache_path
        meta["paths"]["semantic_embedding_cache_path"] = ctx.embedding_cache_path(args.semantic_embedding_model)
        meta["timings_init"] = dict(timings_init)

        config = SessionConfig(
            k=args.k,
            prefilter=args.prefilter,
            min_map_score=args.min_map_score,
            semantic_fallback=args.semantic_fallback,
            semantic_k=args.semantic_k,
            semantic_prefilter=args.semantic_prefilter,
            semantic_min_confidence=args.semantic_min_confidence,
            semantic_embedding_model=args.semantic_embedding_model,
            semantic_resp_mode=args.semantic_resp_mode,
            openai_model=args.openai_model,
            max_assign=args.max_assign,
            assign_prefilter=args.assign_prefilter,
            resp_mode=args.resp_mode,
            seed=args.seed,
            state_keep=args.state_keep,
            year=args.year,
            country=args.country,
            continent=args.continent,
            no_ideology=bool(args.no_ideology),
            require_polar_vectors=bool(args.require_polar_vectors),
            timing=bool(args.timing),
        )

        # Persona initialisation, forced year/geography, initial ideology.
        # build_forced_assignments is resolved at call time so that
        # pipeline_localized.py's deterministic geography still applies.
        try:
            session = DTAGSession(
                ctx=ctx,
                persona=args.persona,
                config=config,
                polar=polar,
                client_factory=default_client_factory,
                forced_assignment_fn=None,  # resolved at call time (pipeline_localized patches it)
                timings_init=timings_init,
            )
        except DTAGConfigError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        timings_init = session.timings_init
        persona = session.persona

        if session.persona_assignments_dropped:
            print(f"WARNING: Dropped initial persona assignments: {session.persona_assignments_dropped[:20]}", file=sys.stderr)

        meta["persona_assignment_rationale"] = session.persona_rationale
        meta["persona_assignments_llm_raw"] = dict(session.persona_assignments_llm_raw)
        meta["persona_assignments_initial"] = dict(session.persona_assignments_initial)
        meta["persona_assignments_dropped"] = list(session.persona_assignments_dropped)
        meta["forced_assignments"] = dict(session.forced_assignments)
        meta["geography"] = dict(session.geo_meta)
        meta["timings_init"] = dict(timings_init)
        meta["ideology_initial"] = session.ideology0

        if args.timing:
            print("TIMING (init)")
            print("-" * 72)
            for k, v in timings_init.items():
                print(f"{k}: {v:.3f}s")
            print()

        def _print_result(result: Dict[str, object]) -> None:
            if result["mapping"]["type"] == "no_match":
                print("NO_MATCH: No semantically relevant survey variable was found; state was not updated.", file=sys.stderr)
                core._section("NO MATCH", "No semantically relevant survey variable was found. The respondent state was not updated.", "91")
                core._section("QUESTION", str(result["question"]).strip(), "90")
                core._section("SELECTION RATIONALE", str(result["display_rationale"]), "90")
                return
            core.pretty_print_output(
                model_path=args.qnet,
                persona_text=persona,
                persona_assignments=dict(session.state),
                var_set=list(result["selected_variables"]),
                rationale_vars=str(result["display_rationale"]),
                var_items=[
                    core.VarItem(variable=a["variable"], question_text=a["survey_question"], response=a["response"])
                    for a in result["anchors"]
                ],
                answer=str(result["answer"]),
                ideology=result["ideology"]["after"],
                timings=result["timings"] if args.timing else None,
            )

        def _run_one(question: str, query_idx: int, source: str) -> None:
            session.query_count = query_idx - 1
            _print_result(session.ask(question, source=source))

        # Execute questions based on mode
        if mode_autoplay:
            qs = core.load_questions_csv(args.autoplay_csv)
            if not qs:
                print(f"ERROR: No questions found in autoplay CSV: {args.autoplay_csv}", file=sys.stderr)
                sys.exit(2)
            for i, q in enumerate(qs, start=1):
                _run_one(q, i, source=f"autoplay:{core._abspath(args.autoplay_csv)}")

        elif mode_loop:
            idx = 0
            for line in sys.stdin:
                q = line.strip()
                if not q:
                    continue
                if q.lower() in {"exit", "quit"}:
                    break
                idx += 1
                _run_one(q, idx, source="stdin")

        else:
            _run_one(args.question.strip(), 1, source="single")

        state = session.state
        records = session.records
        ideology_series = session.ideology_series
        question_series = session.question_series

        # Write final state JSON
        final_state = dict(state)
        with open(final_state_path, "w", encoding="utf-8") as f:
            json.dump(final_state, f, indent=2, ensure_ascii=False)

        # Write ideology time series CSV only when ideology tracking is enabled.
        if ideology_enabled:
            try:
                with open(ideology_csv_path, "w", encoding="utf-8") as f:
                    f.write("step,ideology_index\n")
                    for step, val in ideology_series:
                        if val is not None:
                            f.write(f"{step},{val}\n")
            except Exception as e:
                print(f"WARNING: Failed to write ideology CSV: {e}", file=sys.stderr)

        # Write questions time series CSV
        try:
            with open(questions_csv_path, "w", encoding="utf-8") as f:
                f.write("step,question,source\n")
                for step, q, src in question_series:
                    q_esc = q.replace('"', '""')
                    src_esc = src.replace('"', '""')
                    f.write(f'{step},"{q_esc}","{src_esc}"\n')
        except Exception as e:
            print(f"WARNING: Failed to write questions CSV: {e}", file=sys.stderr)

        meta["ideology_enabled"] = bool(ideology_enabled)
        meta["ideology_disable_reason"] = "" if ideology_enabled else ideology_disable_reason
        meta["ideology_series_length"] = len(ideology_series)
        meta["questions_series_length"] = len(question_series)

        # Write metadata JSON
        meta["records"] = records
        meta["final_state_size"] = len(final_state)
        meta["timings_init"] = dict(timings_init)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # Print outputs
        print("RUN OUTPUTS")
        print("-" * 72)
        print(f"log_file: {log_path}")
        print(f"meta_json: {meta_path}")
        print(f"final_state_json: {final_state_path}")
        print(f"assets_possible_cache: {meta['paths']['possible_cache_path']}")
        print(f"semantic_embedding_cache: {meta['paths']['semantic_embedding_cache_path']}")
        print(f"polar_vectors: {core._abspath(args.polar_vectors) if str(args.polar_vectors or '').strip() else 'disabled'}")
        print(f"ideology_enabled: {ideology_enabled}")
        if ideology_enabled:
            print(f"ideology_csv: {ideology_csv_path}")
        else:
            print(f"ideology_csv: disabled ({ideology_disable_reason})")
        print(f"questions_csv: {questions_csv_path}")
        if mode_autoplay:
            print(f"autoplay_source: {core._abspath(args.autoplay_csv)}")
        print()

    finally:
        try:
            sys.stdout = orig_stdout  # type: ignore[assignment]
            sys.stderr = orig_stderr  # type: ignore[assignment]
        except Exception:
            pass
        try:
            log_fh.close()
        except Exception:
            pass


sys.modules[__name__].__class__ = _CoreAlias


if __name__ == "__main__":
    main()
