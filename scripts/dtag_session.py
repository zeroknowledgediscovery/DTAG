#!/usr/bin/env python3
"""Reusable DTAG respondent session.

This module is the per-respondent core of ``pipeline.py`` extracted into
objects so the command-line pipeline and the web application run the same
code. The algorithm is a line-for-line port of ``pipeline.main()`` steps
(persona initialisation, forced year/geography assignments, direct mapping,
semantic fallback, no-match handling, state updates and ideology geometry);
the LLM helpers and native-LSM helpers are still the functions defined in
``pipeline.py``.

Objects:

* ``SessionConfig``   -- runtime parameters, same defaults as ``pipeline.py``.
* ``ModelContext``    -- model + map data shared by sessions (read-only after
                         construction; caches embeddings per embedding model).
* ``PolarGeometry``   -- polar reference states and d(sL, sR) for ideology.
* ``DTAGSession``     -- one simulated respondent: state, history, ideology.

Survey-response anchors always come from native LSM conditional
distributions. The LLM only selects variables and renders prose.
"""
from __future__ import annotations

import copy
import os
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import pipeline as core


# -----------------------------
# Configuration
# -----------------------------

@dataclass
class SessionConfig:
    """Runtime parameters; defaults match ``pipeline.py``'s argparse defaults."""

    k: int = 6
    prefilter: int = 160
    min_map_score: float = 1.0
    semantic_fallback: str = "answer_only"
    semantic_k: int = 6
    semantic_prefilter: int = 80
    semantic_min_confidence: float = 0.35
    semantic_embedding_model: str = "text-embedding-3-small"
    semantic_resp_mode: str = "max"
    openai_model: str = "gpt-4.1-mini"
    max_assign: int = 8
    assign_prefilter: int = 140
    resp_mode: str = "max"
    seed: int = 1
    state_keep: int = 50
    year: Optional[int] = None
    country: str = ""
    continent: str = ""
    no_ideology: bool = False
    require_polar_vectors: bool = False
    timing: bool = False

    def validate(self) -> None:
        if self.semantic_fallback not in {"off", "answer_only", "update_state"}:
            raise ValueError(f"semantic_fallback must be off|answer_only|update_state, got {self.semantic_fallback!r}")
        if self.resp_mode not in {"max", "draw"}:
            raise ValueError(f"resp_mode must be max|draw, got {self.resp_mode!r}")
        if self.semantic_resp_mode not in {"max", "draw"}:
            raise ValueError(f"semantic_resp_mode must be max|draw, got {self.semantic_resp_mode!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DTAGConfigError(ValueError):
    """Raised when a session cannot be initialised from its configuration."""


# -----------------------------
# Shared model/map context
# -----------------------------

PROVENANCE_COLUMNS = (
    "map_provenance",
    "source",
    "fallback_sources",
    "fallback_n_sources",
    "fallback_consensus_fraction",
    "fallback_support_similarity",
    "fallback_context_f1",
    "fallback_resolution",
)


def load_map_provenance(map_csv: str) -> Dict[str, Dict[str, str]]:
    """Per-variable provenance columns from a semantic map (may be empty)."""
    try:
        df = pd.read_csv(map_csv, dtype=str).fillna("")
    except Exception:
        return {}
    if "variable" not in df.columns:
        return {}
    cols = [c for c in PROVENANCE_COLUMNS if c in df.columns]
    if not cols:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for _, r in df.iterrows():
        v = core.normalize_varname(str(r["variable"]).strip())
        if not v:
            continue
        rec = {c: str(r[c]).strip() for c in cols if str(r[c]).strip()}
        if rec:
            out[v] = rec
    return out


class ModelContext:
    """Native model + semantic map data needed by sessions.

    Constructed once per (model, map) pair and shared by every session that
    uses that pair. Nothing in here is mutated by a session.
    """

    def __init__(
        self,
        model: Any,
        model_path: str,
        map_path: str,
        assets_dir: str,
        possible: Optional[Dict[str, List[str]]] = None,
    ):
        self.model = model
        self.model_path = str(model_path)
        self.map_path = str(map_path)
        self.assets_dir = core._ensure_dir(assets_dir)
        self.timings: Dict[str, float] = {}

        self.feature_names: List[str] = list(model.feature_names)
        self.feat = set(self.feature_names)
        self.idx_map = {self.feature_names[i]: i for i in range(len(self.feature_names))}

        t1 = time.time()
        var_map = core.load_var_map(self.map_path)
        self.var_map: Dict[str, str] = {v: q for v, q in var_map.items() if v in self.feat}
        self.timings["load_map"] = time.time() - t1
        if not self.var_map:
            raise DTAGConfigError(
                "After intersecting map with native model feature_names, no variables remain."
            )
        self.map_provenance = load_map_provenance(self.map_path)

        t2 = time.time()
        if possible is None:
            possible = core.get_possible_responses_cached(model, self.model_path, assets_dir=self.assets_dir)
        self.possible: Dict[str, List[str]] = possible
        self.timings["possible_cache"] = time.time() - t2

        self._emb_lock = threading.Lock()
        self._embeddings: Dict[str, Dict[str, List[float]]] = {}

    @property
    def possible_cache_path(self) -> str:
        return core._abspath(core._possible_cache_path(self.model_path, assets_dir=self.assets_dir, model=self.model))

    def embedding_cache_path(self, embedding_model: str) -> str:
        return core._abspath(core._embedding_cache_path(self.map_path, assets_dir=self.assets_dir, embedding_model=embedding_model))

    def var_embeddings(self, client: Any, embedding_model: str) -> Dict[str, List[float]]:
        """Map embeddings, loaded from the on-disk cache once per context."""
        with self._emb_lock:
            emb = self._embeddings.get(embedding_model)
            if emb is None:
                emb = core.get_var_embeddings_cached(
                    client=client,
                    var_map=self.var_map,
                    map_csv=self.map_path,
                    assets_dir=self.assets_dir,
                    embedding_model=embedding_model,
                )
                self._embeddings[embedding_model] = emb
            return emb


@dataclass
class PolarGeometry:
    enabled: bool = False
    disable_reason: str = ""
    path: str = ""
    left_map: Dict[str, str] = field(default_factory=dict)
    right_map: Dict[str, str] = field(default_factory=dict)
    sL: Optional[np.ndarray] = None
    sR: Optional[np.ndarray] = None
    dLR: float = 0.0
    seconds: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "disable_reason": "" if self.enabled else self.disable_reason,
            "path": core._abspath(self.path) if self.path else "",
            "n_left_assignments": len(self.left_map),
            "n_right_assignments": len(self.right_map),
            "dLR": float(self.dLR) if np.isfinite(self.dLR) else None,
        }


def build_polar_geometry(ctx: ModelContext, polar_path: str, no_ideology: bool = False) -> PolarGeometry:
    """Port of the polar-vector block of ``pipeline.main()``."""
    tpol = time.time()
    polar_path = str(polar_path or "").strip()
    g = PolarGeometry(path=polar_path)
    model = ctx.model

    if no_ideology:
        g.disable_reason = "--no_ideology was set"
    elif not polar_path:
        g.disable_reason = "no --polar_vectors file provided"
    elif not os.path.exists(polar_path):
        g.disable_reason = f"--polar_vectors file not found: {polar_path}"
    else:
        try:
            left_loaded, right_loaded = core.load_polar_vectors_csv(polar_path)
            g.left_map = {v: val for v, val in left_loaded.items() if v in ctx.feat}
            g.right_map = {v: val for v, val in right_loaded.items() if v in ctx.feat}
            if not g.left_map or not g.right_map:
                g.disable_reason = "polar vectors have no usable overlap with this qnet model"
            else:
                g.sL = core.build_pole_vector(model, g.left_map, ctx.idx_map)
                g.sR = core.build_pole_vector(model, g.right_map, ctx.idx_map)
                g.dLR = model.qdistance(g.sL, g.sR)
                if np.isfinite(g.dLR) and g.dLR > 0:
                    g.enabled = True
                else:
                    g.disable_reason = "polar-vector left/right distance is non-finite or zero"
        except Exception as e:
            g.disable_reason = f"failed to load/use polar vectors: {e}"
    g.seconds = time.time() - tpol
    return g


def default_client_factory() -> Any:
    """OpenAI client factory. ``DTAG_LLM_BACKEND=mock`` selects the mock."""
    if os.environ.get("DTAG_LLM_BACKEND", "").strip().lower() == "mock":
        from dtag_mock_llm import MockOpenAI
        return MockOpenAI()
    from openai import OpenAI
    return OpenAI()


# -----------------------------
# Session
# -----------------------------

MAPPING_LABELS = {
    "direct": "DIRECT",
    "semantic_answer_only": "SEMANTIC / ANSWER ONLY",
    "semantic_answer_only_low_confidence": "SEMANTIC / ANSWER ONLY",
    "semantic_update_state": "SEMANTIC / STATE UPDATE",
    "no_match": "NO MATCH",
}


def _sorted_dist(d: Dict[str, float]) -> Dict[str, float]:
    return {k: float(v) for k, v in sorted(d.items(), key=lambda kv: (-float(kv[1]), kv[0]))}


class DTAGSession:
    """One simulated respondent over one native model context.

    Owns all mutable respondent state. Never shares it with other sessions.
    """

    def __init__(
        self,
        ctx: ModelContext,
        persona: str,
        config: SessionConfig,
        polar: Optional[PolarGeometry] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        forced_assignment_fn: Optional[Callable[..., Tuple[Dict[str, str], Dict[str, Any]]]] = None,
        timings_init: Optional[Dict[str, float]] = None,
    ):
        config.validate()
        self.ctx = ctx
        self.config = config
        self.persona_base = str(persona)
        self.polar = polar if polar is not None else PolarGeometry(disable_reason="no --polar_vectors file provided")
        self._client_factory = client_factory or default_client_factory
        self._forced_fn = forced_assignment_fn
        self.lock = threading.RLock()
        self.timings_init: Dict[str, float] = dict(timings_init or {})

        if (not self.polar.enabled) and config.require_polar_vectors:
            raise DTAGConfigError(f"Ideology tracking disabled: {self.polar.disable_reason}")

        self.state: "OrderedDict[str, str]" = OrderedDict()
        self.records: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []
        self.ideology_series: List[Tuple[int, Optional[float]]] = []
        self.question_series: List[Tuple[int, str, str]] = []
        self.query_count = 0
        self._initialize()

    # -- properties --------------------------------------------------------

    @property
    def ideology_enabled(self) -> bool:
        return bool(self.polar.enabled and self.polar.sL is not None and self.polar.sR is not None)

    @property
    def model(self):
        return self.ctx.model

    def _client(self):
        return self._client_factory()

    def _forced(self, **kwargs):
        fn = self._forced_fn or core.build_forced_assignments
        return fn(**kwargs)

    # -- initialisation (pipeline.main steps 5-10) ---------------------------

    def _initialize(self) -> None:
        cfg = self.config
        ctx = self.ctx
        feat = ctx.feat
        possible = ctx.possible
        var_map = ctx.var_map

        persona = self.persona_base
        if cfg.continent:
            persona = f"{persona}\nRegion context: {cfg.continent}"
        if cfg.country:
            persona = f"{persona}\nCountry context: {cfg.country}"
        if cfg.year is not None:
            persona = f"{persona}\nSurvey year: {cfg.year}"
        self.persona = persona

        t3 = time.time()
        p_toks = set(core._tokenize(persona))
        scored_vars = []
        for v in feat:
            opts = possible.get(v, [])
            if not opts:
                continue
            proxy = var_map.get(v, v)
            t = core._norm(proxy)
            t_toks = set(core._tokenize(t))
            overlap = len(p_toks & t_toks)
            scored_vars.append((overlap, v))
        scored_vars.sort(key=lambda x: (x[0], x[1]), reverse=True)
        offer_vars = [v for _, v in scored_vars[: max(1, cfg.assign_prefilter)]]
        allowed_for_llm = {v: possible.get(v, []) for v in offer_vars if possible.get(v, [])}
        self.timings_init["prep_persona_allowed"] = time.time() - t3

        t4 = time.time()
        client_assign = self._client()
        persona_assigns, persona_rationale = core.llm_persona_to_assignments(
            client=client_assign,
            persona_text=persona,
            allowed=allowed_for_llm,
            max_assign=cfg.max_assign,
            model=cfg.openai_model,
        )
        self.timings_init["llm_persona_init"] = time.time() - t4

        t5 = time.time()
        forced_assigns, geo_meta = self._forced(
            feat=feat,
            possible=possible,
            year=cfg.year,
            country=cfg.country,
            continent=cfg.continent,
        )
        self.timings_init["forced_assignments"] = time.time() - t5

        state: "OrderedDict[str, str]" = OrderedDict()
        dropped: List[str] = []
        for v, val in persona_assigns.items():
            if v not in feat:
                dropped.append(f"{v} (not in model)")
                continue
            opts = possible.get(v, [])
            if val not in opts:
                dropped.append(f"{v}={val} (not allowed)")
                continue
            state[v] = val
        for v, val in forced_assigns.items():
            state[v] = val

        self.state = state
        self.persona_rationale = persona_rationale
        self.persona_assignments_llm_raw = dict(persona_assigns)
        self.persona_assignments_initial = dict(state)
        self.persona_assignments_dropped = dropped
        self.forced_assignments = dict(forced_assigns)
        self.geo_meta = dict(geo_meta)

        self.ideology0: Optional[float] = None
        if self.ideology_enabled:
            tI0 = time.time()
            s0 = core.build_full_vector_from_state(self.model, dict(state), ctx.idx_map)
            self.ideology0 = core.ideology_index_from_vectors(s0, self.polar.sL, self.polar.sR, self.model, dLR=self.polar.dLR)
            self.timings_init["ideology_init"] = time.time() - tI0
            self.ideology_series.append((0, self.ideology0))
        else:
            self.timings_init["ideology_init"] = 0.0

        self._initial_state = OrderedDict(state)
        self._initial_ideology_series = list(self.ideology_series)

    # -- reset ---------------------------------------------------------------

    def reset(self) -> None:
        """Return to the initialised respondent without re-running persona init."""
        with self.lock:
            self.state = OrderedDict(self._initial_state)
            self.ideology_series = list(self._initial_ideology_series)
            self.records = []
            self.results = []
            self.question_series = []
            self.query_count = 0

    # -- helpers ported from pipeline.main closures --------------------------

    def _evict_to_limit(self) -> None:
        while len(self.state) > max(1, int(self.config.state_keep)):
            self.state.popitem(last=False)

    def _carry_forward_ideology(self, query_idx: int) -> Optional[float]:
        if self.ideology_enabled and self.ideology_series:
            ideol_prev = self.ideology_series[-1][1]
            self.ideology_series.append((query_idx, ideol_prev))
            return ideol_prev
        return None

    def _compute_and_record_ideology(self, query_idx: int) -> Optional[float]:
        if not self.ideology_enabled:
            return None
        s_vec = core.build_full_vector_from_state(self.model, dict(self.state), self.ctx.idx_map)
        ideol_now = core.ideology_index_from_vectors(s_vec, self.polar.sL, self.polar.sR, self.model, dLR=self.polar.dLR)
        self.ideology_series.append((query_idx, ideol_now))
        return ideol_now

    def _anchor(self, v: str, response: str, dist: Optional[Dict[str, float]]) -> Dict[str, Any]:
        return {
            "variable": v,
            "survey_question": self.ctx.var_map.get(v, ""),
            "response": response,
            "distribution": _sorted_dist(dist or {}),
            "map_provenance": self.ctx.map_provenance.get(v),
        }

    def _finish(
        self,
        record: Dict[str, Any],
        mapping_type: str,
        display_rationale: str,
        var_items: List[core.VarItem],
        dists: Dict[str, Dict[str, float]],
        timings_q: Dict[str, float],
        state_before: Dict[str, str],
        ideology_before: Optional[float],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.records.append(record)
        state_after = dict(self.state)
        evicted = [v for v in state_before if v not in state_after]
        result: Dict[str, Any] = {
            "query_idx": record["query_idx"],
            "question": record["question"],
            "question_source": record["question_source"],
            "answer": record["answer"],
            "selected_variables": list(record["selected_variables"]),
            "selection_rationale": record["selection_rationale"],
            "display_rationale": display_rationale,
            "anchors": [self._anchor(it.variable, it.response, dists.get(it.variable)) for it in var_items],
            "mapping": {
                "type": mapping_type,
                "label": MAPPING_LABELS[mapping_type],
                "direct_mapping": bool(record["direct_mapping"]),
                "semantic_fallback": bool(record["semantic_fallback"]),
                "semantic_fallback_mode": self.config.semantic_fallback,
                "semantic_trigger": record["semantic_trigger"] or None,
                "state_updated": bool(record["state_updates"]),
                "skipped": bool(record["skipped"]),
                "skip_reason": record["skip_reason"] or None,
                "semantic_bridge_items": list(record.get("semantic_bridge_items", [])),
            },
            "state_updates": dict(record["state_updates"]),
            "state_evicted": evicted,
            "state_changed": state_before != state_after,
            "state_size": len(state_after),
            "ideology": {
                "enabled": self.ideology_enabled,
                "before": ideology_before,
                "after": record["ideology_index"],
                "delta": (
                    float(record["ideology_index"]) - float(ideology_before)
                    if record["ideology_index"] is not None and ideology_before is not None
                    else None
                ),
                "initial": self.ideology0,
            },
            "timings": dict(timings_q),
            "record": record,
        }
        if extra:
            result.update(extra)
        self.results.append(result)
        return result

    def _ideology_now(self) -> Optional[float]:
        if self.ideology_enabled and self.ideology_series:
            return self.ideology_series[-1][1]
        return None

    def _record_no_match(
        self,
        question: str,
        query_idx: int,
        source: str,
        rationale: str,
        skip_reason: str,
        timings_q: Dict[str, float],
        state_before: Dict[str, str],
        ideology_before: Optional[float],
    ) -> Dict[str, Any]:
        ideol = self._carry_forward_ideology(query_idx)
        timings_q["total"] = timings_q.get("total", 0.0)
        record = {
            "query_idx": query_idx,
            "question": question,
            "question_source": source,
            "selected_variables": [],
            "selection_rationale": rationale,
            "responses": {},
            "state_updates": {},
            "ideology_index": ideol,
            "answer": "",
            "skipped": True,
            "skip_reason": skip_reason,
            "direct_mapping": False,
            "semantic_fallback": False,
            "semantic_trigger": skip_reason,
            "semantic_state_updated": False,
            "semantic_bridge_items": [],
            "timings": dict(timings_q) if self.config.timing else None,
        }
        return self._finish(
            record, "no_match", rationale.strip() or skip_reason, [], {}, timings_q,
            state_before, ideology_before,
        )

    def _run_semantic_fallback(
        self,
        question: str,
        query_idx: int,
        source: str,
        trigger_reason: str,
        trigger_rationale: str,
        timings_q: Dict[str, float],
        tq0: float,
        state_before: Dict[str, str],
        ideology_before: Optional[float],
    ) -> Dict[str, Any]:
        cfg = self.config
        ctx = self.ctx
        var_map = ctx.var_map
        idx_map = ctx.idx_map
        possible = ctx.possible
        nm = dict(state_before=state_before, ideology_before=ideology_before)

        if cfg.semantic_fallback == "off":
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(question, query_idx, source, trigger_rationale, trigger_reason, timings_q, **nm)

        t = time.time()
        client_sem = self._client()
        try:
            var_embeddings = ctx.var_embeddings(client_sem, cfg.semantic_embedding_model)
            sem_cands = core.semantic_prefilter(
                client=client_sem,
                var_map=var_map,
                question=question,
                top_n=cfg.semantic_prefilter,
                map_csv=ctx.map_path,
                assets_dir=ctx.assets_dir,
                embedding_model=cfg.semantic_embedding_model,
                var_embeddings=var_embeddings,
            )
        except Exception as e:
            timings_q["semantic_prefilter"] = time.time() - t
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source,
                f"{trigger_rationale} Semantic fallback failed during embedding retrieval: {e}",
                "semantic_prefilter_failed", timings_q, **nm,
            )
        timings_q["semantic_prefilter"] = time.time() - t

        if not sem_cands:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source,
                f"{trigger_rationale} No embedding candidates were available for semantic fallback.",
                "semantic_no_candidates", timings_q, **nm,
            )

        t = time.time()
        bridge_block = core.semantic_candidates_text(sem_cands)
        bridge_vars, bridge_rationale, bridge_items, answerable = core.llm_select_semantic_bridge_variables(
            client=client_sem,
            question=question,
            candidates_block=bridge_block,
            k=cfg.semantic_k,
            model=cfg.openai_model,
            min_confidence=cfg.semantic_min_confidence,
        )
        timings_q["semantic_llm_select"] = time.time() - t

        bridge_items = [x for x in bridge_items if str(x.get("variable", "")) in var_map and str(x.get("variable", "")) in idx_map]
        bridge_vars = [v for v in bridge_vars if v in var_map and v in idx_map]
        bridge_items_for_answer = [x for x in bridge_items if str(x.get("variable", "")) in bridge_vars]
        low_confidence_answer_only = False

        if not answerable:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source, bridge_rationale or trigger_rationale,
                "semantic_no_defensible_bridge", timings_q, **nm,
            )

        if not bridge_vars:
            if cfg.semantic_fallback == "answer_only":
                low_conf_items = [
                    x for x in bridge_items
                    if str(x.get("relation_type", "")).strip() != "weak"
                ]
                bridge_vars = list(dict.fromkeys([str(x.get("variable", "")) for x in low_conf_items if str(x.get("variable", ""))]))[: max(1, int(cfg.semantic_k))]
                bridge_items_for_answer = [x for x in low_conf_items if str(x.get("variable", "")) in bridge_vars]
                low_confidence_answer_only = bool(bridge_vars)

            if not bridge_vars:
                timings_q["total"] = time.time() - tq0
                return self._record_no_match(
                    question, query_idx, source, bridge_rationale or trigger_rationale,
                    "semantic_no_defensible_bridge", timings_q, **nm,
                )

        t = time.time()
        NULL_cond = core.build_NULL_with_assignments(self.model, dict(self.state), idx_map)
        dists_cond = core.qnet_conditional_distributions(self.model, NULL_cond, target_vars=bridge_vars)
        bridge_vars = [v for v in bridge_vars if v in dists_cond]
        bridge_items_for_answer = [x for x in bridge_items_for_answer if str(x.get("variable", "")) in bridge_vars]
        timings_q["semantic_native_predict"] = time.time() - t

        if not bridge_vars:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source, bridge_rationale or trigger_rationale,
                "semantic_qnet_no_distribution", timings_q, **nm,
            )

        t = time.time()
        respmap, missing = core.responses_for_vars_from_distributions(
            dists=dists_cond,
            var_set=bridge_vars,
            mode=cfg.semantic_resp_mode,
            seed=cfg.seed + query_idx,
        )
        timings_q["semantic_response"] = time.time() - t
        if missing:
            bridge_vars = [v for v in bridge_vars if v in respmap]
            bridge_items_for_answer = [x for x in bridge_items_for_answer if str(x.get("variable", "")) in bridge_vars]

        if not bridge_vars:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source, bridge_rationale or trigger_rationale,
                "semantic_no_response_for_bridge_variables", timings_q, **nm,
            )

        var_items = [
            core.VarItem(variable=v, question_text=var_map.get(v, ""), response=respmap.get(v, ""))
            for v in bridge_vars
        ]

        updates: Dict[str, str] = {}
        state_updated = (cfg.semantic_fallback == "update_state") and (not low_confidence_answer_only)
        if state_updated:
            t = time.time()
            for v in bridge_vars:
                if v in respmap and respmap[v] in possible.get(v, []):
                    if v in self.state:
                        self.state.move_to_end(v)
                    self.state[v] = respmap[v]
                    updates[v] = respmap[v]
            self._evict_to_limit()
            timings_q["semantic_state_update"] = time.time() - t

            t = time.time()
            ideol = self._compute_and_record_ideology(query_idx)
            timings_q["semantic_ideology"] = time.time() - t
        else:
            ideol = self._carry_forward_ideology(query_idx)

        t = time.time()
        client_final = self._client()
        answer = core.llm_craft_semantic_bridge_answer(
            client=client_final,
            persona_text=self.persona,
            user_question=question,
            var_items=var_items,
            bridge_rationale=bridge_rationale,
            bridge_items=bridge_items_for_answer,
            model=cfg.openai_model,
        )
        timings_q["semantic_llm_final"] = time.time() - t
        timings_q["total"] = time.time() - tq0

        if low_confidence_answer_only:
            mode_label = "SEMANTIC FALLBACK: low-confidence answer only; state not updated"
            mapping_type = "semantic_answer_only_low_confidence"
        else:
            mode_label = "SEMANTIC FALLBACK: state updated" if state_updated else "SEMANTIC FALLBACK: answer only; state not updated"
            mapping_type = "semantic_update_state" if state_updated else "semantic_answer_only"
        display_rationale = f"{mode_label}. Trigger={trigger_reason}. {bridge_rationale}"

        record = {
            "query_idx": query_idx,
            "question": question,
            "question_source": source,
            "selected_variables": list(bridge_vars),
            "selection_rationale": bridge_rationale,
            "responses": {it.variable: it.response for it in var_items},
            "state_updates": updates,
            "ideology_index": ideol,
            "answer": answer,
            "skipped": False,
            "skip_reason": "",
            "direct_mapping": False,
            "semantic_fallback": True,
            "semantic_trigger": trigger_reason,
            "semantic_state_updated": state_updated,
            "semantic_bridge_items": bridge_items_for_answer,
            "semantic_low_confidence_answer_only": bool(low_confidence_answer_only),
            "timings": dict(timings_q) if cfg.timing else None,
        }
        return self._finish(
            record, mapping_type, display_rationale, var_items, dists_cond, timings_q,
            state_before, ideology_before,
            extra={"semantic_candidates": [
                {"variable": v, "similarity": float(s)} for v, _, s in sem_cands[:20]
            ]},
        )

    # -- public question API ---------------------------------------------------

    def ask(self, question: str, source: str = "interactive") -> Dict[str, Any]:
        """Answer one question and evolve the respondent state (``_run_one``)."""
        question = str(question).strip()
        if not question:
            raise ValueError("Question must be non-empty.")
        with self.lock:
            self.query_count += 1
            return self._run_one(question, self.query_count, source)

    def _run_one(self, question: str, query_idx: int, source: str) -> Dict[str, Any]:
        cfg = self.config
        ctx = self.ctx
        var_map = ctx.var_map
        idx_map = ctx.idx_map
        possible = ctx.possible
        timings_q: Dict[str, float] = {}
        tq0 = time.time()
        state_before = dict(self.state)
        ideology_before = self._ideology_now()
        nm = dict(state_before=state_before, ideology_before=ideology_before)

        self.question_series.append((query_idx, question, source))

        t = time.time()
        cands = core.lexical_prefilter(var_map, question, top_n=cfg.prefilter, min_score=cfg.min_map_score)
        timings_q["prefilters"] = time.time() - t

        if not cands:
            return self._run_semantic_fallback(
                question, query_idx, source,
                trigger_reason="no_lexical_candidate",
                trigger_rationale="No direct lexical candidate passed the minimum content-word relevance threshold.",
                timings_q=timings_q, tq0=tq0, **nm,
            )

        cand_block = core.candidates_text(cands)

        t = time.time()
        client_vars = self._client()
        var_set, rationale_vars = core.llm_select_variables(
            client=client_vars,
            question=question,
            candidates_block=cand_block,
            k=cfg.k,
            model=cfg.openai_model,
        )
        timings_q["llm_select"] = time.time() - t

        var_set = [v for v in var_set if v in var_map and v in idx_map]
        if not var_set:
            return self._run_semantic_fallback(
                question, query_idx, source,
                trigger_reason="llm_no_relevant_variable",
                trigger_rationale=rationale_vars,
                timings_q=timings_q, tq0=tq0, **nm,
            )

        t = time.time()
        NULL_cond = core.build_NULL_with_assignments(self.model, dict(self.state), idx_map)
        dists_cond = core.qnet_conditional_distributions(self.model, NULL_cond, target_vars=var_set)
        timings_q["native_predict"] = time.time() - t

        var_set = [v for v in var_set if v in dists_cond]
        if not var_set:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source, rationale_vars,
                "qnet_no_distribution_for_selected_variables", timings_q, **nm,
            )

        t = time.time()
        respmap, missing = core.responses_for_vars_from_distributions(
            dists=dists_cond,
            var_set=var_set,
            mode=cfg.resp_mode,
            seed=cfg.seed + query_idx,
        )
        timings_q["draw"] = time.time() - t
        if missing:
            var_set = [v for v in var_set if v in respmap]

        if not var_set:
            timings_q["total"] = time.time() - tq0
            return self._record_no_match(
                question, query_idx, source, rationale_vars,
                "no_response_for_selected_variables", timings_q, **nm,
            )

        t = time.time()
        updates: Dict[str, str] = {}
        for v in var_set:
            if v in respmap and respmap[v] in possible.get(v, []):
                if v in self.state:
                    self.state.move_to_end(v)
                self.state[v] = respmap[v]
                updates[v] = respmap[v]
        self._evict_to_limit()
        timings_q["state_update"] = time.time() - t

        t = time.time()
        ideol = self._compute_and_record_ideology(query_idx)
        timings_q["ideology"] = time.time() - t

        var_items = [
            core.VarItem(variable=v, question_text=var_map.get(v, ""), response=respmap.get(v, ""))
            for v in var_set
        ]

        t = time.time()
        client_final = self._client()
        answer = core.llm_craft_human_answer(
            client=client_final,
            persona_text=self.persona,
            user_question=question,
            var_items=var_items,
            model=cfg.openai_model,
        )
        timings_q["llm_final"] = time.time() - t
        timings_q["total"] = time.time() - tq0

        record = {
            "query_idx": query_idx,
            "question": question,
            "question_source": source,
            "selected_variables": list(var_set),
            "selection_rationale": rationale_vars,
            "responses": {it.variable: it.response for it in var_items},
            "state_updates": updates,
            "ideology_index": ideol,
            "answer": answer,
            "skipped": False,
            "skip_reason": "",
            "direct_mapping": True,
            "semantic_fallback": False,
            "semantic_trigger": "",
            "semantic_state_updated": False,
            "semantic_bridge_items": [],
            "timings": dict(timings_q) if cfg.timing else None,
        }
        return self._finish(
            record, "direct", rationale_vars, var_items, dists_cond, timings_q,
            state_before, ideology_before,
            extra={"lexical_candidates": len(cands)},
        )

    # -- inspection --------------------------------------------------------------

    def ideology_trajectory(self) -> List[Dict[str, Any]]:
        by_idx = {r["query_idx"]: r for r in self.results}
        out = []
        prev: Optional[float] = None
        for step, val in self.ideology_series:
            r = by_idx.get(step)
            out.append({
                "step": step,
                "ideology": val,
                "delta": (val - prev) if (val is not None and prev is not None) else None,
                "question": r["question"] if r else None,
                "selected_variables": r["selected_variables"] if r else [],
                "anchors": {a["variable"]: a["response"] for a in r["anchors"]} if r else {},
                "mapping": r["mapping"]["label"] if r else "INITIAL",
            })
            prev = val
        return out

    def initial_state(self) -> Dict[str, str]:
        return dict(self._initial_state)

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy({
            "persona": self.persona,
            "persona_base": self.persona_base,
            "config": self.config.to_dict(),
            "initial_state": dict(self._initial_state),
            "current_state": dict(self.state),
            "question_count": self.query_count,
            "persona_assignment_rationale": self.persona_rationale,
            "persona_assignments_llm_raw": self.persona_assignments_llm_raw,
            "persona_assignments_dropped": self.persona_assignments_dropped,
            "forced_assignments": self.forced_assignments,
            "geography": self.geo_meta,
            "ideology_enabled": self.ideology_enabled,
            "ideology_disable_reason": "" if self.ideology_enabled else self.polar.disable_reason,
            "ideology_initial": self.ideology0,
            "ideology_series": [[s, v] for s, v in self.ideology_series],
            "timings_init": dict(self.timings_init),
        })
