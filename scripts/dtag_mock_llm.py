#!/usr/bin/env python3
"""Deterministic stand-in for the OpenAI client used by DTAG.

This is test/demo infrastructure only. It implements the two OpenAI surfaces
DTAG calls -- ``client.responses.create`` and ``client.embeddings.create`` --
so the real DTAG parsing, validation, native-LSM inference, state updates and
ideology geometry can be exercised without network access or an API key.

It never produces survey anchors: anchors always come from native LSM
conditional distributions. It only stands in for the language layer:

* ``variable_selection``: the first ``min(K, 2)`` lexical candidates;
* ``semantic_bridge_selection``: the first two embedding candidates, confidence 0.6;
* ``persona_assignments``: deterministic picks (hash of persona and variable);
* free text: a short, clearly labelled mock answer built from the anchors.

Magic markers in a question steer the mock for tests:

* ``[nomatch]``  -> no direct variables and no defensible semantic bridge;
* ``[semantic]`` -> no direct variables, semantic bridge accepted;
* ``[lowconf]``  -> no direct variables, bridge answerable but below threshold.

Enable in the CLI with ``DTAG_LLM_BACKEND=mock``.
"""
from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace
from typing import Any, Dict, List

MOCK_MODEL_LABEL = "dtag-mock-llm"


def _section(text: str, header: str) -> str:
    idx = text.find(header)
    if idx < 0:
        return ""
    return text[idx + len(header):]


def _user_question(prompt: str) -> str:
    m = re.search(r"USER QUESTION:\n(.*?)\n\n", prompt, flags=re.S)
    return m.group(1) if m else ""


def _candidate_vars(prompt: str) -> List[str]:
    m = re.search(r"CANDIDATES \([^)]*\):\n(.*)$", prompt, flags=re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line.split("\t", 1)[0].strip())
    return out


def _k(prompt: str) -> int:
    m = re.search(r"\nK=(\d+)", prompt)
    return int(m.group(1)) if m else 1


class _Responses:
    def __init__(self, log: List[Dict[str, Any]]):
        self._log = log

    def create(self, model: str, input: str, text: Dict[str, Any] | None = None, temperature: float | None = None, **_: Any):
        name = ""
        if isinstance(text, dict):
            name = str((text.get("format") or {}).get("name", ""))
        self._log.append({"kind": name or "text", "model": model})
        question = _user_question(input)

        if name == "variable_selection":
            if any(tag in question for tag in ("[nomatch]", "[semantic]", "[lowconf]")):
                obj = {"variables": [], "rationale": "mock: no direct candidate accepted"}
            else:
                cands = _candidate_vars(input)
                obj = {
                    "variables": cands[: max(1, min(_k(input), 2))],
                    "rationale": "mock: first lexical candidates",
                }
            return SimpleNamespace(output_text=json.dumps(obj))

        if name == "semantic_bridge_selection":
            cands = _candidate_vars(input)
            if "[nomatch]" in question or not cands:
                obj = {"answerable": False, "variables": [], "rationale": "mock: no defensible bridge"}
            else:
                conf = 0.2 if "[lowconf]" in question else 0.6
                obj = {
                    "answerable": True,
                    "variables": [
                        {
                            "variable": v,
                            "confidence": conf,
                            "relation_type": "related_construct",
                            "rationale": "mock bridge",
                        }
                        for v in cands[: min(2, _k(input))]
                    ],
                    "rationale": "mock: first embedding candidates",
                }
            return SimpleNamespace(output_text=json.dumps(obj))

        if name == "persona_assignments":
            m = re.search(r"MAX_ASSIGN=(\d+)", input)
            max_assign = int(m.group(1)) if m else 0
            allowed = _section(input, "ALLOWED (var<TAB>responses):\n")
            pm = re.search(r"PERSONA:\n(.*?)\n\nALLOWED", input, flags=re.S)
            persona = pm.group(1) if pm else ""
            assigns = []
            for line in allowed.splitlines():
                if len(assigns) >= min(max_assign, 5):
                    break
                parts = line.split("\t", 1)
                if len(parts) != 2:
                    continue
                opts = [o.strip() for o in parts[1].replace(" ...", "").split("; ") if o.strip()]
                if not opts:
                    continue
                h = int(hashlib.sha1(f"{persona}|{parts[0]}".encode()).hexdigest(), 16)
                assigns.append({"variable": parts[0], "value": opts[h % len(opts)]})
            obj = {"assignments": assigns, "rationale": "mock: deterministic persona assignments"}
            return SimpleNamespace(output_text=json.dumps(obj))

        anchors = re.findall(r"VAR=(.*?)\nQUESTION_TEXT=.*?\nRESPONSE=(.*?)\n", input, flags=re.S)
        summary = "; ".join(f"{v.strip()}={r.strip()}" for v, r in anchors)
        return SimpleNamespace(output_text=f"[MOCK LLM ANSWER] My view follows these anchors: {summary}.")


class _Embeddings:
    DIM = 64

    def __init__(self, log: List[Dict[str, Any]]):
        self._log = log

    def _vec(self, text: str) -> List[float]:
        v = [0.0] * self.DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.DIM] += 1.0
        return v

    def create(self, model: str, input: List[str], **_: Any):
        self._log.append({"kind": "embeddings", "model": model, "n": len(input)})
        return SimpleNamespace(data=[SimpleNamespace(embedding=self._vec(t)) for t in input])


class MockOpenAI:
    """Minimal OpenAI-compatible client with deterministic behaviour."""

    def __init__(self, *_, **__):
        self.calls: List[Dict[str, Any]] = []
        self.responses = _Responses(self.calls)
        self.embeddings = _Embeddings(self.calls)
