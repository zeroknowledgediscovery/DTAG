"""Neutral study question generation, including incomplete source excerpts.

The source excerpt is retained verbatim as provenance. LLM-completed wording
is an experimental reformulation, NOT a verified original GSS question.
"""
from __future__ import annotations

import re


# Verified against the NORC 2024 English ballot, Ballot 3, PDF page 45
# (zero-indexed 44). NATENVIY is the alternative wording: "The environment",
# not NATENVIR's "Improving and protecting the environment".
NATENVIY_BALLOT_REFERENCE = (
    "Are we spending too much, too little, or about the right amount on the environment?"
)
NATENVIY_BALLOT_URL = (
    "https://gss.norc.org/content/dam/gss/get-documentation/pdf/quex/"
    "GSS2024_Ballot3_English.pdf"
)


def verified_natenviy_reference(item):
    """Use an audited form-specific source only for the known defective excerpt."""
    return (
        item.item_id == "natenviy"
        and item.source_text_incomplete
        and item.original_wording.strip().casefold() == "improving and protecting the environment"
        and {c.native_value.casefold() for c in item.choices}
        == {"too much", "too little", "about right"}
    )


def validates_natenviy_form(question):
    """Fail closed on wrong topic, missing spending scale, or NATENVIR wording.

    Reverse-mapping a question cannot identify its form when near-duplicate GSS
    variables describe the same topic. The exact verified respondent-facing
    wording and response scale are a safer reference for this form.
    """
    q = question.casefold()
    return (
        q.endswith("?")
        and re.search(r"\benvironment\b", q) is not None
        and re.search(r"\b(?:spend\w*|spent|expenditure|expenditures)\b", q) is not None
        and all(phrase in q for phrase in ("too much", "too little"))
        and re.search(r"\b(?:right|appropriate)\b", q) is not None
        and re.search(r"\b(?:improv\w*|protect\w*)\b", q) is None
    )


class QuestionGenerationError(RuntimeError):
    """No semantically validated complete wording is available to present."""

    def __init__(self, message, *, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


class QuestionLLM:
    def __init__(self, adapter, config, backend="mock"):
        self.adapter, self.config, self.backend = adapter, config, backend
        if backend == "mock":
            from dtag_mock_llm import MockOpenAI
            self.client = MockOpenAI()
        elif backend == "openai":
            from openai import OpenAI
            self.client = OpenAI(timeout=30, max_retries=0)
        else:
            raise ValueError("unknown LLM backend")

    def generate(self, item):
        import dtag_core as core
        from optimizer.dtag_bridge import map_question, RUN_DEFAULTS
        incomplete = item.source_text_incomplete
        # NATENVIY's GSS map label omits its spending stem AND incorrectly
        # borrows NATENVIR's alternate wording. Use the verified 2024 form as
        # the LLM input, retaining the actual model/map label as provenance.
        anchored = verified_natenviy_reference(item)
        source = NATENVIY_BALLOT_REFERENCE if anchored else item.original_wording
        attempts = []
        for _ in range(2):
            try:
                kwargs = {"source_incomplete": True} if incomplete else {}
                text = core.llm_craft_survey_question(
                    self.client,
                    source,
                    [c.display_label for c in item.choices],
                    self.config.llm_model,
                    **kwargs,
                ).strip()
                # Shared helper silently returns its input on provider failure.
                # Never claim that fallback wording came from the live LLM.
                if incomplete and (text == source.strip() or
                                   not text.endswith("?") or len(text) < 15):
                    attempts.append({"text": text, "mapper_hit": False,
                                     "rejected": "incomplete_or_unrewritten_source"})
                    continue
                if anchored:
                    # NATENVIY and NATENVIR are separate questionnaire forms.
                    # The global text->variable mapper need not identify the
                    # correct form even for a perfectly valid question.
                    valid = validates_natenviy_form(text)
                    attempts.append({"text": text, "mapper_hit": False,
                                     "verified_source_match": valid,
                                     "rejected": None if valid else "wrong_2024_wording_form_or_scale"})
                    if valid:
                        return self.record(text, item, attempts, False, None,
                                           validation_method="verified_2024_form_specific_reference_v1",
                                           source_reference=NATENVIY_BALLOT_URL)
                    continue

                mapping = map_question(
                    self.adapter.world, self.client, text, self.config.llm_model,
                    {**RUN_DEFAULTS, "k": 1},
                )
                hit = mapping["variables"] == [item.item_id]
                attempts.append({"text": text, "mapped_ids": mapping["variables"], "mapper_hit": hit,
                                 "canonical_returned": text == item.original_wording})
                if hit:
                    return self.record(
                        text, item, attempts, text == item.original_wording,
                        "canonical wording returned by core (provider may have fallen back)"
                        if text == item.original_wording else None,
                    )
            except Exception as e:
                attempts.append({"error": type(e).__name__})
        if incomplete:
            raise QuestionGenerationError(
                "unable to generate a complete, validated question from the source excerpt",
                attempts=attempts,
            )
        return self.record(item.original_wording, item, attempts, True,
                           "mapping ambiguous or provider unavailable")

    def record(self, text, item, attempts, fallback, reason, *, validation_method="direct_reverse_mapping", source_reference=None):
        return {"displayed_wording": text, "question_provenance": {
            "provider": self.backend, "llm_id": self.config.llm_model,
            "prompt_version": self.config.prompt_version, "input_item_id": item.item_id,
            "source_text_incomplete": item.source_text_incomplete,
            "wording_status": ("llm_rephrasing_of_verified_2024_ballot"
                               if source_reference and not fallback
                               else "llm_completion_of_unverified_excerpt"
                               if item.source_text_incomplete and not fallback
                               else "source_or_rephrasing"),
            "validation_method": validation_method,
            "source_reference": source_reference,
            "attempts": attempts, "mapper_hit": bool(attempts and attempts[-1].get("mapper_hit")),
            "cache_hit": False, "fallback": fallback, "fallback_reason": reason}}
