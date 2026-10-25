"""Narrow native facade. Model/geometry only; no synthetic session is constructed."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from . import ROOT
from .study_config import digest

MISSING = re.compile(r"^(?:i?a?p|iap|dk|na|n/a|d/k|don't know|dont know|do not know|no answer|not applicable|not available|refus(?:ed|al)|skipped|not on web|not on ballot)(?:$|\b)", re.I)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeAdapter:
    def __init__(self, config):
        from optimizer.dtag_bridge import World, canonical_map, ensure_model
        from optimizer.one_step_geometry import strict_native_index
        self.lock = threading.RLock()
        model_path = ensure_model(config.model_key, os.environ.get("DTAG_MODEL_ROOT"))
        poles = ROOT / "assets/polar_vectors/gss/gss_2024_polar_vectors.csv"
        self.world = World(str(model_path), str(canonical_map(config.model_key)), str(poles),
                           os.environ.get("DTAG_ASSETS_DIR", str(Path.home() / ".cache/dtag/assets")))
        self._index = strict_native_index
        files = sorted(p for p in model_path.rglob("*") if p.is_file())
        identity = [(str(p.relative_to(model_path)), file_hash(p)) for p in files]
        self.provenance = {"model_key": config.model_key, "model_release": config.model_release,
                           "model_content_sha256": digest(identity), "map_sha256": file_hash(self.world.map_path),
                           "poles_sha256": file_hash(poles), "pole_configuration": self.world.poles_summary(),
                           "core_question_prompt_sha256": file_hash(ROOT / "scripts/dtag_core.py"),
                           "native_binary_sha256": file_hash(__import__("dtag_lsm").__file__),
                           "code_commit": os.environ.get("DTAG_CODE_COMMIT") or
                               subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
        self.index({})  # Fail readiness on invalid native geometry.

    def support(self, variable):
        return self.world.ctx.possible.get(variable, [])

    def validate_config(self, config):
        for item in config.items:
            if item.item_id not in self.world.ctx.var_map:
                raise ValueError(f"missing model/map item: {item.item_id}")
            for c in item.choices:
                if c.native_value not in self.support(item.item_id) or MISSING.search(c.native_value):
                    raise ValueError(f"invalid/missing native category: {item.item_id}={c.native_value}")
        if len(self.eligible(config)) < config.intervention_steps:
            raise ValueError("insufficient eligible items for configured intervention length")

    def eligible(self, config):
        from optimize_question_sets import askable
        ctx, g = self.world.ctx, self.world.g
        skip = set(g.left_map) | set(g.right_map) | set(config.excluded_ids) | set(config.ethics_disallowed_ids)
        return sorted(i.item_id for i in config.bank("intervention") if i.item_id not in skip
                      and i.item_id in ctx.var_map and i.item_id in ctx.idx_map
                      and askable(i.item_id, ctx.var_map[i.item_id], ctx.feat)
                      and all(c.native_value in self.support(i.item_id) and not MISSING.search(c.native_value)
                              for c in i.choices))

    def webapp_candidates(self, state, config, exclusions=()):
        """Exactly the webapp's opinion-item universe, not the YAML instrument.

        Reuse optimizer.session_push.askable_items with a minimal session facade;
        do not copy its filtering rules into human_study.
        """
        from types import SimpleNamespace
        from optimizer.session_push import askable_items
        session = SimpleNamespace(
            ctx=self.world.ctx, polar=self.world.g, state=dict(state)
        )
        skip = (set(exclusions) | set(config.excluded_ids) |
                set(config.ethics_disallowed_ids) |
                {i.item_id for i in config.bank("outcome")} |
                {i.item_id for i in config.bank("baseline")})
        vars_ = askable_items(session, include_pole_items=False)
        return {v: list(self.support(v)) for v in vars_
                if v not in skip}

    def webapp_scores(self, state, candidates):
        """Use same native_one_step implementation as webapp push suggestions."""
        from optimizer.one_step_geometry import native_one_step
        with self.lock:
            return native_one_step(self.world, dict(state), only=candidates)

    def dynamic_item(self, variable):
        """Materialize one selected native variable only when needed."""
        from types import SimpleNamespace
        from .study_config import Choice
        ctx = self.world.ctx
        if variable not in ctx.var_map or variable not in ctx.idx_map:
            raise ValueError("native item has no semantic-map question")
        values = list(self.support(variable))
        if not values:
            raise ValueError("native item has no supported categories")
        return SimpleNamespace(
            item_id=variable, original_wording=str(ctx.var_map[variable]),
            source_text_incomplete=True,
            choices=tuple(Choice(native_value=str(v), display_label=str(v))
                          for v in values),
            phase="intervention", required=True,
            version="native-map-runtime",
        )

    def webapp_mapping_items(self, displayed_question, answer, target, config):
        """Webapp lexical prefilter over full native map, plus question target.

        The shared mapper supplies candidate *identifiers*, never answers;
        evidence-backed free-text LLM mapping then validates native categories.
        No predeclared YAML intervention whitelist is used.
        """
        from optimizer.dtag_bridge import RUN_DEFAULTS
        import dtag_core as core
        allowed = set(self.webapp_candidates({}, config)) | {
            x.item_id for x in config.bank("baseline")}
        phrase = displayed_question + "\\n" + answer
        found = core.lexical_prefilter(
            self.world.ctx.var_map, phrase,
            top_n=int(RUN_DEFAULTS["prefilter"]),
            min_score=float(RUN_DEFAULTS["min_map_score"]),
        )
        vars_ = list(dict.fromkeys([target] + [v for v, _ in found]))
        return {v: (config.item(v) if v in {i.item_id for i in config.bank("baseline")}
                    else self.dynamic_item(v))
                for v in vars_ if v in allowed}

    def index(self, state):
        with self.lock:
            return self._index(self.world, state)

    def distributions(self, state, variables):
        from optimizer.one_step_geometry import native_distributions
        with self.lock:
            return native_distributions(self.world, state, variables)

    def scores(self, state, candidates):
        from optimizer.one_step_geometry import one_step_geometry, native_extension_indices, has_fast_extensions
        with self.lock:
            return one_step_geometry(state, candidates, lambda ss: [self.index(s) for s in ss],
                                     self.distributions, text=self.world.text,
                                     extension_fn=(lambda s, ps: native_extension_indices(self.world, s, ps))
                                     if has_fast_extensions(self.world) else None)
