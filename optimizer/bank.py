"""Candidate question bank.

A bank entry is ``{"id", "question", "source_variables", "variables", "mapping", ...}`` where
``variables`` are the survey items the question is answered with in simulation.

Sources (``bank.source``):

* ``map``  - the model's opinion items (respondent facts, identity, self-placement and survey
             meta-data excluded), worded from the semantic map, optionally rewritten by the LLM
             into natural questions (``bank.rewrite: true``);
* ``file`` - your own JSONL/CSV with a ``question`` column and optional ``source_variables``
             (``;``-separated in CSV, a list in JSONL); compatible with the question banks of
             ``applications/question_sequence_optimization``.

Mapping (``bank.mapping``), done once per question and cached:

* ``source`` - use ``source_variables`` as given (no LLM);
* ``dtag``   - map the question through DTAG's own direct mapper (lexical prefilter + LLM variable
               selection, as the web app does) and use the selected variables;
* ``verify`` - like ``dtag``, but keep the question only if DTAG selects at least
               ``min_source_recall`` of its source variables.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dtag_bridge import REPO, JsonCache, World, map_question, sha256

sys.path.insert(0, str(REPO / "scripts"))
from optimize_question_sets import askable  # noqa: E402  (the reviewed opinion-item filter)

# Identity and respondent facts in plain question wording (codebook-era maps phrase them as
# questions, e.g. "Was your sex recorded as male or female at birth?"). Asking these would
# overwrite who a participant is rather than probe an opinion.
IDENTITY = re.compile(
    r"\b(your|you) (sex|gender|age|race|ethnic|religion|religious preference|sexual|orientation|birth|born)|"
    r"\b(sex|gender) (recorded|assigned|at birth|now)|sexual orientation|\bwere you born\b|how old|year .*born|"
    r"\b(are|were) you (currently )?(married|divorced|widowed|employed|working|a citizen|registered)|"
    r"how many (children|brothers|sisters|people)|highest (year|degree|grade)|\bincome\b|\bwhat is your\b|"
    r"\bdid you vote\b|\bwho did you vote\b|\bvoted\b|best describes you", re.I)
# Demographic / fact variables by name, for items whose wording alone does not give them away.
IDENTITY_VARS = re.compile(r"^(sex(ornt|now|birth|bth)?|gender|age|race|racecen|ethnic|hispanic|born|birth|"
                           r"educ|degree|marital|childs|sibs|income|rincom|wrkstat|occ|indus|vote|pres|uscitzn|citizen|parcit|fucitzn)\d*$", re.I)

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {"variable": {"type": "string"}, "question": {"type": "string"}},
        "required": ["variable", "question"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}

REWRITE_PROMPT = """You are writing survey questions for a research simulation.
For each survey item below, write ONE natural, neutral question that a person could be asked and
whose answer is exactly what the item measures. Keep the item's meaning and response scale; do not
add persuasion, framing, facts or opinions; do not merge items. Keep it under 40 words.
Return JSON with one entry per item, using the item's variable name exactly.

ITEMS (- variable<TAB>survey wording<TAB>answer options):
{items}
"""


def _clean(text: str) -> str:
    """Collapse whitespace; codebook labels in capitals become sentence case."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if t.isupper():
        return t.capitalize()
    return t[:1].upper() + t[1:]


def from_map(world: World, max_items: Optional[int] = None, include: Optional[List[str]] = None,
             exclude: Optional[List[str]] = None, participant_vars: Optional[set] = None) -> List[Dict[str, Any]]:
    """Opinion items of the model. Never includes a variable that defines any participant."""
    feat = set(world.ctx.feat)
    inc, exc = set(include or []), set(exclude or []) | set(participant_vars or [])
    rows = []
    for v in world.ctx.feat:
        t = world.text.get(v, "")
        if v in exc or (inc and v not in inc) or not t or t.lower() == v.lower():
            continue
        if not inc and (not askable(v, t, feat) or IDENTITY.search(t) or IDENTITY_VARS.match(v)):
            continue
        if not world.ctx.possible.get(v):
            continue
        rows.append({"id": v, "question": _clean(t), "source_variables": [v], "survey_wording": t})
    return rows[:max_items] if max_items else rows


def rewrite(world: World, llm: Any, rows: List[Dict[str, Any]], batch: int = 15, log=print) -> List[Dict[str, Any]]:
    """LLM rewrite of survey wording into natural questions (one per item, meaning preserved)."""
    out = []
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        items = "\n".join(
            f"- {r['source_variables'][0]}\t{r['survey_wording']}\t{'; '.join(world.ctx.possible.get(r['source_variables'][0], [])[:8])}"
            for r in chunk)
        obj = json.loads(llm.complete(REWRITE_PROMPT.format(items=items), schema=REWRITE_SCHEMA,
                                      schema_name="question_rewrite", temperature=0.3))
        got = {str(q.get("variable")): str(q.get("question", "")).strip() for q in obj.get("questions", [])}
        for r in chunk:
            q = got.get(r["source_variables"][0])
            out.append({**r, "question": q or r["question"], "rewritten": bool(q)})
        log(f"  rewrite {min(i + batch, len(rows))}/{len(rows)}")
    return out


def load_file(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    rows: List[Dict[str, Any]] = []
    if p.suffix.lower() == ".jsonl":
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    else:
        with open(p, encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    out = []
    for i, r in enumerate(rows):
        q = str(r.get("question", "")).strip()
        if not q:
            continue
        sv = r.get("source_variables") or r.get("variables") or r.get("variable") or []
        if isinstance(sv, str):
            sv = [s.strip() for s in re.split(r"[;,|]", sv) if s.strip()]
        out.append({"id": str(r.get("id") or f"q{i + 1:04d}"), "question": q, "source_variables": list(sv)})
    return out


def map_bank(world: World, client: Any, llm_model: str, rows: List[Dict[str, Any]], mode: str,
             run: Dict[str, Any], cache: JsonCache, min_source_recall: float = 0.5, log=print) -> List[Dict[str, Any]]:
    """Resolve each question to the survey variables used in simulation (see module docstring)."""
    out, dropped = [], 0
    map_sha = sha256(Path(world.map_path))  # a changed map invalidates cached mappings
    for i, r in enumerate(rows):
        if mode == "source":
            vs = [v for v in r.get("source_variables", []) if v in world.ctx.idx_map and world.ctx.possible.get(v)]
            if vs:
                out.append({**r, "variables": vs, "mapping": "source"})
            else:
                dropped += 1
            continue
        k = cache.key("map", map_sha, r["question"], run["k"], run["prefilter"], run["min_map_score"], llm_model)
        m = cache.get(k)
        if m is None:
            m = map_question(world, client, r["question"], llm_model, run)
            cache.put(k, m)
        src = set(r.get("source_variables") or [])
        recall = (len(src & set(m["variables"])) / len(src)) if src else None
        rec = {**r, "variables": m["variables"], "mapping": m["mapping"], "source_recall": recall}
        keep = bool(m["variables"]) and (mode == "dtag" or recall is None or recall >= min_source_recall)
        if keep:
            out.append(rec)
        else:
            dropped += 1
        if (i + 1) % 25 == 0:
            log(f"  mapped {i + 1}/{len(rows)}")
    log(f"bank: {len(out)} usable questions ({dropped} dropped: no usable survey variable"
        f"{' or below source recall' if mode == 'verify' else ''})")
    return out


def save(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
