#!/usr/bin/env python3
"""
Generate a reusable bank of natural-language intervention questions for DTAG.

The LLM is used here only to turn real survey items into readable, contemporary
questions. Each generated question retains the exact source variables that
ground it, so the subsequent Monte Carlo optimizer can bypass repeated LLM
mapping and run entirely against the native LSM.

Example:
  python applications/question_sequence_optimization/generate_question_bank.py \
      --map maps/gss/gss_2024_map.csv \
      --out outputs/qseq/gss2024_question_bank.jsonl \
      --target 240 --questions_per_batch 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
from openai import OpenAI


DEFAULT_EXCLUDE = re.compile(
    r"(respondent id|case id|ballot|version|weight|sampl|interview|month of|"
    r"day of|year of|occupation code|industry code|prestige|longitude|latitude)",
    re.I,
)


def clean_text(x: object) -> str:
    s = re.sub(r"\s+", " ", str(x or "")).strip()
    return s


def load_items(map_csv: str, min_chars: int, max_chars: int) -> List[Dict[str, str]]:
    df = pd.read_csv(map_csv, dtype=str).fillna("")
    if "variable" not in df.columns:
        raise ValueError("semantic map must contain a 'variable' column")
    text_col = "question_text_filled" if "question_text_filled" in df.columns else "question_text"
    if text_col not in df.columns:
        raise ValueError("semantic map must contain question_text or question_text_filled")

    out: List[Dict[str, str]] = []
    seen = set()
    for _, r in df.iterrows():
        v = clean_text(r["variable"]).lower()
        q = clean_text(r[text_col])
        if not v or not q or v in seen:
            continue
        if len(q) < min_chars or len(q) > max_chars:
            continue
        if DEFAULT_EXCLUDE.search(q):
            continue
        if q.upper() == q and len(q.split()) <= 6:
            continue
        seen.add(v)
        out.append({"variable": v, "survey_item": q})
    return out


def batched(items: List[Dict[str, str]], n: int) -> Iterable[List[Dict[str, str]]]:
    for i in range(0, len(items), n):
        yield items[i:i+n]


def call_llm(client: OpenAI, model: str, batch: List[Dict[str, str]], n_questions: int) -> List[Dict]:
    payload = "\n".join(f"- {x['variable']}: {x['survey_item']}" for x in batch)
    system = (
        "You design intervention questions for a scientific survey digital-twin experiment. "
        "Return JSON only. Questions must be ordinary natural-language questions a person could "
        "actually be asked; do not mention survey variable names, GSS, models, latent space, or "
        "predicted ideology. Each question must be defensibly grounded in 1-3 supplied variables. "
        "Prefer attitudes, policy, institutions, religion, rights, immigration, inequality, social "
        "trust, civic life, morality, family, work, welfare, crime, science, and public spending. "
        "Avoid pure demographics and factual biography. Make questions semantically distinct."
    )
    user = f"""Create up to {n_questions} candidate intervention questions from this batch.

For every question return:
- question: natural-language question
- source_variables: list of 1-3 exact variable names from the batch
- rationale: one short sentence explaining the grounding
- domain: short topical label

Source items:
{payload}

Return an object of the form {{"questions":[...]}}."""
    r = client.chat.completions.create(
        model=model,
        temperature=0.7,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    obj = json.loads(r.choices[0].message.content)
    qs = obj.get("questions", [])
    return qs if isinstance(qs, list) else []


def normalize_generated(rows: List[Dict], allowed: Dict[str, str], batch_id: int) -> List[Dict]:
    out = []
    for j, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        q = clean_text(row.get("question"))
        vs = row.get("source_variables", [])
        if isinstance(vs, str):
            vs = [vs]
        vs = [clean_text(v).lower() for v in vs if clean_text(v).lower() in allowed]
        vs = list(dict.fromkeys(vs))[:3]
        if len(q) < 20 or not vs:
            continue
        if not q.endswith("?"):
            q += "?"
        out.append({
            "id": f"b{batch_id:03d}_q{j:02d}",
            "question": q,
            "source_variables": vs,
            "source_items": [allowed[v] for v in vs],
            "domain": clean_text(row.get("domain")) or "other",
            "rationale": clean_text(row.get("rationale")),
        })
    return out


def dedupe(rows: List[Dict]) -> List[Dict]:
    out = []
    seen_q = set()
    seen_vars = set()
    for r in rows:
        qk = re.sub(r"\W+", " ", r["question"].lower()).strip()
        vk = tuple(sorted(r["source_variables"]))
        if qk in seen_q:
            continue
        # allow multiple phrasings only when variable group differs
        if vk in seen_vars and len(vk) == 1:
            continue
        seen_q.add(qk)
        seen_vars.add(vk)
        out.append(r)
    for i, r in enumerate(out, 1):
        r["id"] = f"q{i:04d}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("DTAG_OPENAI_MODEL", "gpt-4.1-mini"))
    ap.add_argument("--target", type=int, default=240)
    ap.add_argument("--batch_items", type=int, default=36)
    ap.add_argument("--questions_per_batch", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--min_chars", type=int, default=18)
    ap.add_argument("--max_chars", type=int, default=420)
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise SystemExit("OPENAI_API_KEY is required")

    items = load_items(args.map, args.min_chars, args.max_chars)
    rng = random.Random(args.seed)
    rng.shuffle(items)
    client = OpenAI()

    generated: List[Dict] = []
    for bi, batch in enumerate(batched(items, args.batch_items), 1):
        allowed = {x["variable"]: x["survey_item"] for x in batch}
        try:
            rows = call_llm(client, args.model, batch, args.questions_per_batch)
            generated.extend(normalize_generated(rows, allowed, bi))
        except Exception as e:
            print(f"[warn] batch {bi} failed: {e}")
        if len(dedupe(generated)) >= args.target:
            break

    final = dedupe(generated)[: args.target]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in final:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    meta = {
        "map": str(Path(args.map).resolve()),
        "model": args.model,
        "seed": args.seed,
        "eligible_source_items": len(items),
        "generated_questions": len(final),
    }
    out.with_suffix(out.suffix + ".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
