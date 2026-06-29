#!/usr/bin/env python3
"""
Minimal OpenAI API smoke test for DTAG pipelines.

Checks the two API patterns used in pipeline6/pipeline6iloc:
  1) plain Responses API text generation
  2) Responses API strict JSON-schema structured output

Usage:
  export OPENAI_API_KEY=...
  python3 openai_dtag_smoketest.py --model gpt-4.1-mini
  python3 openai_dtag_smoketest.py --model gpt-4.1 --list-models

Exit code is nonzero if any required check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from typing import Any


def die(msg: str, code: int = 2) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(code)


def safe_get_output_text(resp: Any) -> str:
    if hasattr(resp, "output_text") and isinstance(resp.output_text, str):
        return resp.output_text.strip()
    parts = []
    try:
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                txt = getattr(c, "text", None)
                if isinstance(txt, str):
                    parts.append(txt)
    except Exception:
        pass
    return "".join(parts).strip()


def print_exception(e: BaseException) -> None:
    print("ERROR_TYPE:", type(e).__name__, file=sys.stderr)
    for attr in ("status_code", "code", "type", "param", "request_id"):
        val = getattr(e, attr, None)
        if val is not None:
            print(f"ERROR_{attr.upper()}:", val, file=sys.stderr)
    msg = getattr(e, "message", None)
    if msg:
        print("ERROR_MESSAGE:", msg, file=sys.stderr)
    else:
        print("ERROR_MESSAGE:", str(e), file=sys.stderr)


def timed(label: str, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"{label}: FAIL after {dt:.3f}s", file=sys.stderr)
        print_exception(e)
        if os.environ.get("DTAG_SMOKETEST_TRACEBACK") == "1":
            traceback.print_exc()
        raise
    dt = time.perf_counter() - t0
    print(f"{label}: OK in {dt:.3f}s")
    return out, dt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
                    help="Model to test. Default: OPENAI_MODEL or gpt-4.1-mini")
    ap.add_argument("--list-models", action="store_true",
                    help="Also list models visible to this API key")
    ap.add_argument("--skip-structured", action="store_true",
                    help="Only test plain generation")
    ap.add_argument("--skip-plain", action="store_true",
                    help="Only test structured output")
    ap.add_argument("--max-models", type=int, default=40)
    args = ap.parse_args()

    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        die("OPENAI_API_KEY is not set in this shell/environment")
    print(f"OPENAI_API_KEY: set, length={len(key)}, prefix={key[:7]}...")
    print(f"MODEL: {args.model}")

    try:
        import openai  # type: ignore
        from openai import OpenAI  # type: ignore
    except Exception as e:
        print_exception(e)
        die("Could not import openai. Try: pip install -U openai")

    print("openai package:", getattr(openai, "__version__", "unknown"))
    client = OpenAI()

    if args.list_models:
        def _list():
            return client.models.list()
        try:
            models, _ = timed("models.list", _list)
            ids = sorted([getattr(m, "id", "") for m in getattr(models, "data", []) if getattr(m, "id", "")])
            print(f"Visible models, first {args.max_models} of {len(ids)}:")
            for mid in ids[: args.max_models]:
                print("  ", mid)
            if args.model not in set(ids):
                print(f"WARNING: requested model '{args.model}' was not found in models.list output", file=sys.stderr)
        except Exception:
            die("models.list failed", 1)

    if not args.skip_plain:
        def _plain():
            return client.responses.create(
                model=args.model,
                input="Return exactly the string: DTAG_API_OK",
                max_output_tokens=32,
            )
        try:
            resp, _ = timed("responses.create plain", _plain)
            txt = safe_get_output_text(resp)
            print("PLAIN_OUTPUT:", repr(txt))
            if "DTAG_API_OK" not in txt:
                print("WARNING: plain output did not contain expected marker", file=sys.stderr)
        except Exception:
            die("plain Responses API call failed", 1)

    if not args.skip_structured:
        schema = {
            "type": "object",
            "properties": {
                "variables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                },
                "rationale": {"type": "string"},
            },
            "required": ["variables", "rationale"],
            "additionalProperties": False,
        }

        prompt = (
            "Task: map a user question to survey variables.\n"
            "Choose variables from the candidate list only. Return JSON only.\n\n"
            "USER QUESTION:\nWhat do you think about gun control?\n\n"
            "CANDIDATES:\n"
            "GUNLAW\tWould you favor or oppose a law requiring a police permit before a person could buy a gun?\n"
            "ABANY\tShould abortion be legal for any reason?\n"
            "POLVIEWS\tPolitical views from liberal to conservative\n"
        )

        def _structured():
            return client.responses.create(
                model=args.model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "variable_selection",
                        "schema": schema,
                        "strict": True,
                    }
                },
                max_output_tokens=300,
            )

        try:
            resp, _ = timed("responses.create structured json_schema", _structured)
            txt = safe_get_output_text(resp)
            print("STRUCTURED_RAW:", repr(txt))
            obj = json.loads(txt)
            print("STRUCTURED_PARSED:", json.dumps(obj, indent=2))
            if not obj.get("variables"):
                die("structured output parsed but variables is empty", 1)
        except json.JSONDecodeError as e:
            print_exception(e)
            die("structured call returned non-JSON text", 1)
        except Exception:
            die("structured Responses API call failed", 1)

    print("PASS: OpenAI API calls needed by DTAG pipeline are working for this model/environment.")


if __name__ == "__main__":
    main()
