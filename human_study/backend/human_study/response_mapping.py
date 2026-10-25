"""Shared DTAG webapp question-to-variable mapping for a human written response.

Variable discovery MUST use DTAGSession.map_question() exactly; when lexical
matching does not produce a variable, it uses the identical dtag_core semantic
embedding and bridge functions as DTAGSession._run_semantic_fallback() with
semantic_fallback='update_state'. No category values or synthetic LSM draws
are generated here: a *human* answered, and the recorded words alone supply
the labels in QuestionLLM.interpret_multi.
"""
from __future__ import annotations

from types import SimpleNamespace


def shared_session_config(llm_model):
    from dtag_session import SessionConfig
    from dtag_config import load_config
    from . import ROOT

    # Match DTAGEngine.session_config: instantiate SessionConfig and overlay
    # the actual webapp's configs/dtag_config.yaml defaults.run, NOT the
    # dataclass fallback defaults. E.g. webapp maps k=50/prefilter=200.
    # No survey/candidate defaults are duplicated in the human study.
    run = (load_config(ROOT / "configs/dtag_config.yaml")
           .get("defaults", {}).get("run", {}))
    cfg = SessionConfig()
    for name, value in run.items():
        if hasattr(cfg, name):
            setattr(cfg, name, value)
    cfg.openai_model = llm_model
    cfg.resp_mode = "draw"
    cfg.semantic_fallback = "update_state"
    # Keep semantic_resp_mode from the webapp's actual run configuration;
    # it is a separate parameter from resp_mode (currently 'max').
    cfg.validate()
    return cfg


def map_human_response(world, client, llm_model, displayed_question, written_answer):
    """Return DTAG-selected model variable IDs and full mapping provenance."""
    import dtag_core as core
    from dtag_session import DTAGSession

    cfg = shared_session_config(llm_model)
    ctx = world.ctx
    # Webapp's map_question expects a session with ctx, config, _client.
    # The shared method itself has no state or persona dependencies.
    mapping_session = SimpleNamespace(
        ctx=ctx, config=cfg, _client=lambda: client,
    )
    # The recorded answer supplies additional expressed topics to the same
    # webapp question mapper. Never force the selected target into the output.
    text = displayed_question + "\n" + written_answer
    direct = DTAGSession.map_question(mapping_session, text)
    if direct["variables"]:
        return {
            "variables": direct["variables"],
            "path": "webapp_direct_mapping",
            "rationale": direct["rationale"],
            "semantic_fallback": cfg.semantic_fallback,
            "semantic_resp_mode": cfg.semantic_resp_mode,
            "response_mode": cfg.resp_mode,
            "candidate_count": len(direct["candidates"]),
            "source": "dtag_session.DTAGSession.map_question",
        }
    # Original webapp's semantic bridge when no lexical candidates or the
    # LLM says no relevant variable: SAME embedding retrieval, prefilter
    # and LLM bridge functions/threshold as _run_semantic_fallback().
    try:
        var_embeddings = ctx.var_embeddings(client, cfg.semantic_embedding_model)
        semantic = core.semantic_prefilter(
            client=client, var_map=ctx.var_map, question=text,
            top_n=cfg.semantic_prefilter, map_csv=ctx.map_path,
            assets_dir=ctx.assets_dir,
            embedding_model=cfg.semantic_embedding_model,
            var_embeddings=var_embeddings,
        )
    except Exception as exc:
        raise RuntimeError("DTAG semantic bridge unavailable") from exc
    if not semantic:
        return {
            "variables": [], "path": "webapp_semantic_no_candidates",
            "rationale": direct["reason"], "semantic_fallback": cfg.semantic_fallback,
            "semantic_resp_mode": cfg.semantic_resp_mode,
            "response_mode": cfg.resp_mode, "candidate_count": 0,
            "source": "dtag_core.semantic_prefilter",
        }
    bridge_vars, rationale, bridge_items, answerable = core.llm_select_semantic_bridge_variables(
        client=client, question=text,
        candidates_block=core.semantic_candidates_text(semantic),
        k=cfg.semantic_k, model=cfg.openai_model,
        min_confidence=cfg.semantic_min_confidence,
    )
    # Match DTAGSession._run_semantic_fallback native/map filtering.
    variables = list(dict.fromkeys(v for v in bridge_vars
                      if v in ctx.var_map and v in ctx.idx_map)) if answerable else []
    return {
        "variables": variables,
        "path": "webapp_semantic_update_state" if variables else "webapp_semantic_no_defensible_bridge",
        "rationale": rationale,
        "semantic_fallback": cfg.semantic_fallback,
        "semantic_resp_mode": cfg.semantic_resp_mode,
        "response_mode": cfg.resp_mode,
        "candidate_count": len(semantic),
        "bridge_items": [x for x in bridge_items
                         if str(x.get("variable")) in variables],
        "source": "dtag_core.semantic_prefilter+llm_select_semantic_bridge_variables",
    }
