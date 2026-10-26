"""Source-grounded, per-variable human-study question generation (not DTAG selection).

No changes to native optimization, model states, candidate filtering or mapping.
This module reconstructs the respondent-facing question *after* selection,
using the 2024 codebook excerpt (if packaged), reviewed wording contract, and
the COMPLETE model-native answer alphabet. Failure is explicit, not invention.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from . import ROOT

CATALOG = ROOT / "human_study" / "data" / "gss_2024_r2_source_context.json"

# Avoid interpreting GSS reserved codes as ordinary response alternatives.
RESERVED = re.compile(
    r"^(?:i?a?p|n/a|d/k|don'?t know|no answer|not available|"
    r"not on ballot|skipped on web|refus(?:ed|al)|not applicable)\b", re.I,
)
CHOICE_CUE = re.compile(
    r"(?:\b(?:following|these|the listed|those)\s+"
    r"(?:ranges?|brackets?|options?|choices?|alternatives?|"
    r"income groups?|groups?|statements?)\b|"
    r"\b(?:options?|choices?|ranges?|brackets?)\s+(?:include|are|listed|below)\b)",
    re.I,
)
ORPHAN_CUE = re.compile(
    r"\b(?:the following|these (?:options?|ranges?|groups?|statements?)|"
    r"such a person|this person|the above|the previous question)\b", re.I,
)
TOKEN_NORMALIZE = re.compile(r"[^a-z0-9$]+")


@lru_cache(maxsize=1)
def catalog():
    """Load a source snapshot pinned to this release, never make network calls."""
    if not CATALOG.exists():
        return {}
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if data.get("model_key") != "gss/gss_2024" or data.get("schema_version") != "1":
        raise ValueError("incorrect 2024 codebook catalog version")
    entries = data.get("variables")
    if not isinstance(entries, dict):
        raise ValueError("malformed codebook context catalog")
    return entries


def source_entry(variable):
    """Only independently retrieved source entries, not inferred context."""
    return catalog().get(str(variable).casefold(), {})


def source_digest(variable):
    row = source_entry(variable)
    if not row:
        return None
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def clean_answers(choices):
    # Retain every real native answer as given. Never truncate at 15 or
    # reorder/algebraically recode the underlying model categories.
    out = []
    for c in choices:
        name = str(getattr(c, "display_label", getattr(c, "native_value", c))).strip()
        if name and name not in out and not RESERVED.match(name):
            out.append(name)
    return out


def normalize(value):
    return TOKEN_NORMALIZE.sub(" ", str(value).lower()).strip()


def response_requirements(source, choices):
    """Return exact options when a question requires an unseen list/card.

    A thermometer with 101 numeric possibilities is a scale, not a showcard;
    do not print hundreds of numeric answers. Instead, a source contract
    must preserve its zero/midpoint/endpoints.
    """
    opts = clean_answers(choices)
    required = bool(CHOICE_CUE.search(source))
    # More than 9 textual/range categories must be made available even if
    # the source happens to omit the phrase "these options".
    textual_large = len(opts) >= 10 and not all(
        re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*", o) for o in opts
    )
    return opts if (required or textual_large) else []


def validate_complete_choices(text, source, choices):
    """Check every referenced option actually appears in displayed wording."""
    required = response_requirements(source, choices)
    if not required:
        return []
    shown = normalize(text)
    missing = [c for c in required if normalize(c) not in shown]
    return missing


def has_unresolved_choice_reference(text, source, choices):
    """Disallow 'the following ranges' without the corresponding values."""
    if not ORPHAN_CUE.search(text):
        return False
    opts = clean_answers(choices)
    if not opts:
        return True
    # A later "such a person" is valid if a preceding sentence introduced
    # that person. Do not reject genuine source-complete NORC vignettes.
    if re.search(r"\b(?:the above|the previous question)\b", text, re.I):
        return True
    pronoun = re.search(r"\b(?:such a person|this person)\b", text, re.I)
    if pronoun:
        preceding = text[:pronoun.start()]
        if not re.search(
            r"\b(?:clergyman|woman|man|individual|citizen|person|"
            r"applicant|worker|adult|speaker|employee|religious leader)\b",
            preceding, re.I,
        ):
            return True
    return bool(validate_complete_choices(text, text, choices))


def make_prompt(variable, mapped_text, authoritative_source, responses,
                *, contract_reference=None, feedback=(), original_codebook=None):
    """Build the prompt from exact evidence, marking what has not been reviewed."""
    entry = original_codebook if original_codebook is not None else source_entry(variable)
    codebook_excerpt = str(entry.get("excerpt") or "").strip()
    pages = entry.get("pdf_pages") or []
    contract_note = (
        f"Reviewed GSS source contract; citation: {contract_reference}\n"
        if contract_reference else "No verified item-specific wording contract exists.\n"
    )
    if not codebook_excerpt:
        codebook_excerpt = "UNAVAILABLE. Do not pretend to know the original ballot context."
    elif len(codebook_excerpt) > 6000:
        codebook_excerpt = codebook_excerpt[:6000] + "\n[EXCERPT TRUNCATED; remaining context not verified]"
    items = "\n".join(f"  {i+1}. {v}" for i, v in enumerate(responses))
    required = response_requirements(authoritative_source, responses)
    notes = "\n".join(f"- {f}" for f in feedback) if feedback else "None"
    return (
        "TASK: Rewrite exactly ONE already selected GSS 2024 variable for a human respondent. "
        "This is wording reconstruction, not selection or model inference.\n"
        "You must preserve the measured construct, population, premise, time period, "
        "response task, ordering, and direction of all scale anchors.\n"
        "No preceding interview screens or response cards are visible to this participant.\n"
        "Rules:\n"
        "1. Write a complete, neutral, independently understandable question. "
        "You MAY use multiple sentences when needed for instructions, a vignette, "
        "response alternatives, a ranking card, or applicability. The LAST sentence "
        "must end with '?'. Do NOT force everything into one sentence.\n"
        "2. If your question mentions 'the following', 'these options', ranges, "
        "ranking positions, a scale, or a card, provide the actual options/anchors "
        "in the displayed question. Do not rely on an invisible list.\n"
        "3. If applicability depends on an earlier answer, state the condition "
        "explicitly (e.g., a third race only for a person naming three races). "
        "Do not assert that the condition is true for this respondent.\n"
        "4. Use the supplied native response strings as evidence; preserve meanings, "
        "including numeric range endpoints and mutually exclusive alternatives. "
        "Do not invent new categories or subtly change the measurement.\n"
        "5. If the map and source documentation leave out an essential referent, "
        "premise or response mapping that cannot be recovered from these inputs, "
        "set missing_context=true and return question=''. Never guess.\n"
        "6. The semantic map is a label, not necessarily the original questionnaire. "
        "The codebook excerpt, if present, can itself refer to missing interviewer "
        "cards or prior screens. Do not call your reconstruction verbatim.\n"
        "7. Never ask for identifying details; do not mention variable names, "
        "models or codebooks in participant-facing text.\n\n"
        f"TARGET VARIABLE (internal only): {variable}\n"
        f"CANONICAL SEMANTIC MAP LABEL: {mapped_text}\n"
        f"BEST AVAILABLE RESTORED SOURCE: {authoritative_source}\n"
        f"SOURCE STATUS: {contract_note}"
        f"2024 GSS RELEASE-2 CODEBOOK EXCERPT (PDF pages {pages}):\n"
        f"{codebook_excerpt}\n\n"
        f"ALL {len(responses)} MODEL-NATIVE RESPONSES, NO TRUNCATION:\n{items}\n\n"
        + ("You MUST include every one of these response alternatives explicitly "
           "in the displayed question, because the task requires a visible list: "
           + " | ".join(required) + "\n\n"
           if required else
           "Express response scale and endpoint meanings where relevant, "
           "without mechanically enumerating numeric thermometer points.\n\n")
        + f"VALIDATION FAILURES TO CORRECT ON THIS RETRY:\n{notes}\n"
        "Return strict JSON with 'question' (string), 'missing_context' (boolean), "
        "and 'missing_details' (string). 'missing_context' is true only if you "
        "cannot construct a faithful respondent question from the provided evidence."
    )


def craft_question(client, model, variable, mapped_text, authoritative_source,
                   responses, *, contract_reference=None, feedback=()):
    """One live LLM request. Provider failure propagates to the caller."""
    from dtag_core import _get_output_text
    entry = source_entry(variable)
    prompt = make_prompt(
        variable, mapped_text, authoritative_source, responses,
        contract_reference=contract_reference, feedback=feedback,
        original_codebook=entry,
    )
    schema = {
        "type": "object", "properties": {
            "question": {"type": "string"},
            "missing_context": {"type": "boolean"},
            "missing_details": {"type": "string"},
        },
        "required": ["question", "missing_context", "missing_details"],
        "additionalProperties": False,
    }
    res = client.responses.create(
        model=model, input=prompt,
        text={"format": {
            "type": "json_schema",
            "name": "human_study_grounded_wording_v1",
            "schema": schema, "strict": True,
        }},
    )
    obj = json.loads(_get_output_text(res))
    if not isinstance(obj, dict) or not isinstance(obj.get("question"), str) or (
        not isinstance(obj.get("missing_context"), bool)
    ) or not isinstance(obj.get("missing_details"), str):
        raise ValueError("malformed source-grounded question object")
    return obj
