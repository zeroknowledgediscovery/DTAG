"""Provider-neutral LLM access for the optimizer and for DTAG's own language steps.

Every backend implements one small interface::

    llm.complete(prompt, schema=None, schema_name="response", temperature=0.2) -> str
    llm.embed(texts) -> list[list[float]]          # optional (semantic fallback only)

and ``DTAGClient(llm)`` adapts it to the two OpenAI calls DTAG's core makes
(``client.responses.create`` with a JSON schema, ``client.embeddings.create``), so DTAG's
real persona decoding and question-to-variable mapping run on any backend.

Backends (``llm.provider`` in the config):

* ``openai``    any OpenAI-compatible endpoint: OpenAI, Azure OpenAI, OpenRouter, Together,
                Groq, vLLM, LM Studio, Ollama (``base_url``), via the ``openai`` package;
* ``anthropic`` Anthropic Messages API over HTTPS (no extra package);
* ``command``   any CLI agent or tool: the prompt goes to stdin, the reply is read from stdout
                (e.g. ``claude -p``, ``llm -m ...``, ``ollama run ...``, your own agent script);
* ``python``    any Python callable ``"package.module:function"`` with the ``complete`` signature,
                for agent frameworks or custom routing;
* ``mock``      deterministic, offline (DTAG's mock client) for tests and dry runs.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

JSON_INSTRUCTION = (
    "\n\nReturn ONLY a JSON object (no markdown, no commentary) that conforms to this JSON schema:\n{schema}\n"
)


def parse_json(text: str) -> Any:
    """Parse the first JSON object in a model reply (tolerates code fences and surrounding prose)."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    while start != -1:
        depth = 0
        in_str = esc = False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except Exception:
                        break
        start = t.find("{", start + 1)
    raise ValueError(f"No JSON object found in model reply: {t[:200]!r}")


class LLM:
    """Base class. Subclasses implement ``_raw(prompt, schema, schema_name, temperature) -> str``."""

    name = "llm"
    model = ""

    def __init__(self, retries: int = 2):
        self.retries = retries
        self.calls = 0

    def _raw(self, prompt: str, schema: Optional[dict], schema_name: str, temperature: float) -> str:
        raise NotImplementedError

    def complete(self, prompt: str, schema: Optional[dict] = None, schema_name: str = "response",
                 temperature: float = 0.2) -> str:
        """Text reply; with ``schema``, a validated JSON string."""
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                self.calls += 1
                out = self._raw(prompt, schema, schema_name, temperature)
                if schema is None:
                    return out
                return json.dumps(parse_json(out), ensure_ascii=False)
            except Exception as e:  # malformed JSON or transient API error: retry
                last = e
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
        raise RuntimeError(f"{self.name} ({self.model}) failed after {self.retries + 1} attempts: {last}")

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            f"The {self.name} backend has no embeddings; DTAG's semantic fallback is unavailable "
            "(direct mapping, which the optimizer uses, does not need it).")

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.name, "model": self.model}


class OpenAICompatible(LLM):
    name = "openai"

    def __init__(self, model: str, base_url: Optional[str] = None, api_key_env: str = "OPENAI_API_KEY",
                 embedding_model: Optional[str] = "text-embedding-3-small", timeout: float = 120, **kw: Any):
        super().__init__(**kw)
        from openai import OpenAI  # in DTAG's requirements

        key = os.environ.get(api_key_env) or ("not-needed" if base_url else None)
        if not key:
            raise RuntimeError(f"Set {api_key_env} (or give base_url for a local OpenAI-compatible server).")
        self.client = OpenAI(api_key=key, base_url=base_url or None, timeout=timeout)
        self.model, self.base_url, self.embedding_model = model, base_url, embedding_model
        self._schema_mode = "json_schema"  # downgraded automatically if the server rejects it

    def _raw(self, prompt, schema, schema_name, temperature):
        messages = [{"role": "user", "content": prompt}]
        if schema is None:
            r = self.client.chat.completions.create(model=self.model, messages=messages, temperature=temperature)
            return r.choices[0].message.content or ""
        if self._schema_mode == "json_schema":
            try:
                r = self.client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature,
                    response_format={"type": "json_schema",
                                     "json_schema": {"name": schema_name, "schema": schema, "strict": True}})
                return r.choices[0].message.content or ""
            except Exception as e:
                if "response_format" not in str(e) and "json_schema" not in str(e) and "400" not in str(e):
                    raise
                self._schema_mode = "json_object"
        if self._schema_mode == "json_object":
            try:
                r = self.client.chat.completions.create(
                    model=self.model, temperature=temperature, response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt + JSON_INSTRUCTION.format(schema=json.dumps(schema))}])
                return r.choices[0].message.content or ""
            except Exception as e:
                if "response_format" not in str(e) and "400" not in str(e):
                    raise
                self._schema_mode = "prompt"
        r = self.client.chat.completions.create(
            model=self.model, temperature=temperature,
            messages=[{"role": "user", "content": prompt + JSON_INSTRUCTION.format(schema=json.dumps(schema))}])
        return r.choices[0].message.content or ""

    def embed(self, texts):
        if not self.embedding_model:
            return super().embed(texts)
        r = self.client.embeddings.create(model=self.embedding_model, input=list(texts))
        return [d.embedding for d in r.data]

    def describe(self):
        return {"provider": self.name, "model": self.model, "base_url": self.base_url}


class Anthropic(LLM):
    name = "anthropic"

    def __init__(self, model: str, api_key_env: str = "ANTHROPIC_API_KEY",
                 base_url: str = "https://api.anthropic.com", max_tokens: int = 4096, timeout: float = 180, **kw: Any):
        super().__init__(**kw)
        self.key = os.environ.get(api_key_env)
        if not self.key:
            raise RuntimeError(f"Set {api_key_env} for the anthropic provider.")
        self.model, self.base_url, self.max_tokens, self.timeout = model, base_url.rstrip("/"), max_tokens, timeout

    def _raw(self, prompt, schema, schema_name, temperature):
        content = prompt if schema is None else prompt + JSON_INSTRUCTION.format(schema=json.dumps(schema))
        body = json.dumps({"model": self.model, "max_tokens": self.max_tokens, "temperature": temperature,
                           "messages": [{"role": "user", "content": content}]}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1/messages", data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic API {e.code}: {e.read()[:300]!r}") from None
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class Command(LLM):
    """Any CLI agent: prompt on stdin, reply on stdout."""

    name = "command"

    def __init__(self, command: str, model: str = "", timeout: float = 600, **kw: Any):
        super().__init__(**kw)
        if not command:
            raise RuntimeError("llm.command is required for the command provider.")
        self.command, self.model, self.timeout = command, model or command.split()[0], timeout

    def _raw(self, prompt, schema, schema_name, temperature):
        content = prompt if schema is None else prompt + JSON_INSTRUCTION.format(schema=json.dumps(schema))
        p = subprocess.run(shlex.split(self.command), input=content, capture_output=True, text=True, timeout=self.timeout)
        if p.returncode != 0:
            raise RuntimeError(f"command exited {p.returncode}: {p.stderr[-400:]}")
        return p.stdout

    def describe(self):
        return {"provider": self.name, "command": self.command}


class PythonCallable(LLM):
    """``callable: "pkg.module:function"`` with signature f(prompt, schema=None, schema_name=..., temperature=...) -> str.
    An optional ``embed`` attribute on the function provides embeddings."""

    name = "python"

    def __init__(self, callable: str, model: str = "", **kw: Any):
        super().__init__(**kw)
        mod, _, fn = callable.partition(":")
        if not fn:
            raise RuntimeError("llm.callable must look like 'package.module:function'.")
        self.fn: Callable[..., str] = getattr(importlib.import_module(mod), fn)
        self.model, self.target = model or callable, callable

    def _raw(self, prompt, schema, schema_name, temperature):
        return self.fn(prompt, schema=schema, schema_name=schema_name, temperature=temperature)

    def embed(self, texts):
        e = getattr(self.fn, "embed", None)
        return e(list(texts)) if e else super().embed(texts)

    def describe(self):
        return {"provider": self.name, "callable": self.target}


def _default_for(schema: Dict[str, Any]) -> Any:
    """Smallest value that satisfies a JSON schema (offline mock replies to unknown prompts)."""
    t = schema.get("type")
    if t == "object":
        return {k: _default_for(v) for k, v in (schema.get("properties") or {}).items() if k in schema.get("required", [])}
    return {"array": [], "string": "", "boolean": True, "number": 0, "integer": 0}.get(t, None)


class Mock(LLM):
    """Offline and deterministic. DTAG's own calls go to DTAG's mock client; the optimizer's
    question-rewrite call echoes the survey wording."""

    name = "mock"

    def __init__(self, model: str = "mock", **kw: Any):
        super().__init__(retries=0)
        from dtag_mock_llm import MockOpenAI

        self.model, self._dtag = model, MockOpenAI()

    def _raw(self, prompt, schema, schema_name, temperature):
        if schema_name == "question_rewrite":
            items = re.findall(r"^- (\S+)\t(.+?)\t", prompt, flags=re.M)
            return json.dumps({"questions": [{"variable": v, "question": t.strip()} for v, t in items]})
        if schema is not None and schema_name not in ("variable_selection", "semantic_bridge_selection", "persona_assignments"):
            return json.dumps(_default_for(schema))
        r = self._dtag.responses.create(model=self.model, input=prompt, temperature=temperature,
                                        text={"format": {"type": "json_schema", "name": schema_name, "schema": schema or {}}}
                                        if schema else None)
        return getattr(r, "output_text", "")

    def embed(self, texts):
        return [d.embedding for d in self._dtag.embeddings.create(model="mock", input=list(texts)).data]


PROVIDERS = {"openai": OpenAICompatible, "anthropic": Anthropic, "command": Command,
             "python": PythonCallable, "mock": Mock}


def make_llm(cfg: Dict[str, Any]) -> LLM:
    """Build a backend from the ``llm`` section of the config."""
    cfg = dict(cfg or {})
    provider = str(cfg.pop("provider", "openai")).lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown llm.provider {provider!r}; choose one of {sorted(PROVIDERS)}")
    cfg = {k: v for k, v in cfg.items() if v is not None}
    return PROVIDERS[provider](**cfg)


class DTAGClient:
    """OpenAI-shaped adapter so DTAG's core (``scripts/dtag_core.py``) can use any backend."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.responses = SimpleNamespace(create=self._responses_create)
        self.embeddings = SimpleNamespace(create=self._embeddings_create)

    def _responses_create(self, model: str, input: str, text: Optional[dict] = None,
                          temperature: Optional[float] = None, **_: Any):
        fmt = (text or {}).get("format") or {}
        schema = fmt.get("schema") if fmt.get("type") == "json_schema" else None
        out = self.llm.complete(input, schema=schema, schema_name=fmt.get("name", "response"),
                                temperature=0.2 if temperature is None else float(temperature))
        return SimpleNamespace(output_text=out)

    def _embeddings_create(self, model: str, input: List[str], **_: Any):
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in self.llm.embed(list(input))])
