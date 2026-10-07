#!/usr/bin/env python3
"""
One-time validation that generated natural-language questions map back to their
retained GSS grounding under DTAG's normal LLM semantic mapper.

This does NOT sample responses or mutate respondent state. It only checks the
mapping stage, so accepted questions can subsequently be optimized with the
fast native mapped Monte Carlo loop.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pipeline as core
from dtag_engine import DTAGEngine


def read_bank(path: str) -> List[Dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def map_question(sess, question: str) -> Dict:
    cfg, ctx = sess.config, sess.ctx
    cands = core.lexical_prefilter(ctx.var_map, question, top_n=cfg.prefilter,
                                   min_score=cfg.min_map_score)
    if cands:
        client = sess._client()
        selected, rationale = core.llm_select_variables(
            client=client,
            question=question,
            candidates_block=core.candidates_text(cands),
            k=cfg.k,
            model=cfg.openai_model,
        )
        selected = [v for v in selected if v in ctx.var_map and v in ctx.idx_map]
        if selected:
            return {"mapping": "direct", "selected_variables": selected, "rationale": rationale}

    client = sess._client()
    embeddings = ctx.var_embeddings(client, cfg.semantic_embedding_model)
    sem = core.semantic_prefilter(
        client=client,
        var_map=ctx.var_map,
        question=question,
        top_n=cfg.semantic_prefilter,
        map_csv=ctx.map_path,
        assets_dir=ctx.assets_dir,
        embedding_model=cfg.semantic_embedding_model,
        var_embeddings=embeddings,
    )
    if not sem:
        return {"mapping": "none", "selected_variables": [], "rationale": "no semantic candidates"}

    bridge, rationale, items, answerable = core.llm_select_semantic_bridge_variables(
        client=client,
        question=question,
        candidates_block=core.semantic_candidates_text(sem),
        k=cfg.semantic_k,
        model=cfg.openai_model,
        min_confidence=cfg.semantic_min_confidence,
    )
    bridge = [v for v in bridge if v in ctx.var_map and v in ctx.idx_map]
    return {
        "mapping": "semantic" if answerable and bridge else "none",
        "selected_variables": bridge,
        "rationale": rationale,
        "bridge_items": items,
    }


def overlap_metrics(source: List[str], selected: List[str]) -> Dict:
    a, b = set(source), set(selected)
    inter = a & b
    return {
        "source_overlap_n": len(inter),
        "source_recall": len(inter) / max(1, len(a)),
        "selected_precision": len(inter) / max(1, len(b)),
        "exact_variable_set": a == b,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question_bank", required=True)
    ap.add_argument("--out", required=True, help="Validated JSONL")
    ap.add_argument("--profile", default="gss2024_cm")
    ap.add_argument("--min_source_recall", type=float, default=0.5)
    ap.add_argument("--require_direct", action="store_true")
    args = ap.parse_args()

    rows = read_bank(args.question_bank)
    engine = DTAGEngine()
    es = engine.create_session(
        profile=args.profile,
        overrides={"semantic_fallback": "update_state", "resp_mode": "draw",
                   "semantic_resp_mode": "draw"},
    )
    sess = es.session

    accepted, report = [], []
    for i, row in enumerate(rows, 1):
        m = map_question(sess, row["question"])
        met = overlap_metrics(row.get("source_variables", []), m["selected_variables"])
        ok = met["source_recall"] >= args.min_source_recall
        if args.require_direct:
            ok = ok and m["mapping"] == "direct"
        rr = {
            "id": row.get("id"),
            "question": row["question"],
            "source_variables": row.get("source_variables", []),
            **m,
            **met,
            "accepted": bool(ok),
        }
        report.append(rr)
        if ok:
            x = dict(row)
            x["validation"] = {
                "mapping": m["mapping"],
                "selected_variables": m["selected_variables"],
                **met,
            }
            accepted.append(x)
        print(f"[{i}/{len(rows)}] {row.get('id')} {m['mapping']} recall={met['source_recall']:.2f} accepted={ok}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in accepted:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    out.with_suffix(out.suffix + ".report.json").write_text(
        json.dumps({
            "profile": args.profile,
            "input_n": len(rows),
            "accepted_n": len(accepted),
            "acceptance_rate": len(accepted) / max(1, len(rows)),
            "criteria": {
                "min_source_recall": args.min_source_recall,
                "require_direct": args.require_direct,
            },
            "questions": report,
        }, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
