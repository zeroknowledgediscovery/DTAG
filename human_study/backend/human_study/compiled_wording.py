"""Immutable, post-selection source-wording lookup for the human study.

This does NOT choose or exclude GSS coordinates, read the participant state,
map free text, or make native-model predictions. An exact-match miss returns
None and the unchanged source-grounded LLM generation path handles the item.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from . import ROOT
from .grounded_generation import (
    has_unresolved_choice_reference, validate_complete_choices,
)
from .wording_contracts import (
    context_for_native_item, validates_standalone, validates_wording,
)

CATALOG_PATH = ROOT / "human_study/data/gss_2024_compiled_wording.json"
CATALOG_VERSION = "1"
MODEL_KEY = "gss/gss_2024"
MODEL_RELEASE = "v0.2.1"
# The catalog is a presentation index, not an opinion-item eligibility filter.
ALLOWED_CERTIFICATIONS = frozenset(("source_contract", "human_reviewed"))


def fingerprint(values):
    """Stable source/answer fingerprint; order and numeric value retained."""
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def native_values(item):
    return [str(c.native_value) for c in item.choices]


def labels(item):
    return [str(c.display_label) for c in item.choices]


def entry_for(item, text, *, certification, source_reference=None):
    """Create the exact keyed record used by the compiler and runtime."""
    return {
        "variable": str(item.item_id),
        "model_release": MODEL_RELEASE,
        "source_map_sha256": fingerprint(str(item.original_wording)),
        "native_answers_sha256": fingerprint(native_values(item)),
        "display_labels_sha256": fingerprint(labels(item)),
        "question": text,
        "certification": certification,
        "source_reference": source_reference,
    }


@lru_cache(maxsize=1)
def catalog():
    if not CATALOG_PATH.is_file():
        return None
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if (raw.get("schema_version") != CATALOG_VERSION
            or raw.get("model_key") != MODEL_KEY
            or raw.get("model_release") != MODEL_RELEASE
            or raw.get("total_native_variables") != 811
            or not isinstance(raw.get("entries"), dict)
            or raw.get("catalog_revision_sha256") != fingerprint(raw.get("entries", {}))):
        # Wrong release or stale/malformed catalog MUST NOT be accepted.
        raise ValueError("compiled GSS wording catalog incompatible with model")
    return raw


def lookup(item, config):
    """Return prevalidated wording for the exact selected variable or None.

    A hit is allowed only when release, source-map label, native values and
    their displayed labels match the compilation artifact exactly. Nothing
    falls through to another variable; nothing is removed from selection.
    """
    if (getattr(config, "model_key", None) != MODEL_KEY
            or getattr(config, "model_release", None) != MODEL_RELEASE
            or getattr(config, "candidate_mode", None) != "native_webapp"):
        return None
    data = catalog()
    if data is None:
        return None
    entry = data["entries"].get(str(item.item_id))
    if not entry or entry.get("certification") not in ALLOWED_CERTIFICATIONS:
        return None
    expected = entry_for(
        item, entry["question"], certification=entry["certification"],
        source_reference=entry.get("source_reference"),
    )
    if any(entry.get(k) != expected[k] for k in (
        "variable", "model_release", "source_map_sha256",
        "native_answers_sha256", "display_labels_sha256",
    )):
        return None
    question = entry["question"]
    if not isinstance(question, str) or not validates_standalone(question):
        return None
    contract = context_for_native_item(item.item_id, labels(item))
    if entry["certification"] == "source_contract":
        if contract is None or question != contract.source:
            # An audited contract changed since compilation; do not accept.
            return None
    if contract and not validates_wording(
        item.item_id, question, contract_override=contract,
    ):
        return None
    source = contract.source if contract else str(item.original_wording)
    if validate_complete_choices(question, source, item.choices):
        return None
    if has_unresolved_choice_reference(question, source, item.choices):
        return None
    return {
        "displayed_wording": question,
        "question_provenance": {
            "provider": "compiled-source",
            "llm_id": None,
            "prompt_version": "offline-compiled-wording-v1",
            "item_version": getattr(item, "version", None),
            "input_item_id": item.item_id,
            "source_text_incomplete": item.source_text_incomplete,
            "wording_status": "prevalidated_standalone_source",
            "validation_method": "versioned_source_catalog_exact_match_v1",
            "source_reference": entry.get("source_reference"),
            "catalog_revision_sha256": data.get("catalog_revision_sha256"),
            "certification": entry["certification"],
            "mapper_hit": None,
            "cache_hit": True,
            "fallback": False,
            "generation_attempts": 0,
            "attempts": [],
        },
    }
