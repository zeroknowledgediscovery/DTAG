"""Neutral study question generation, including incomplete source excerpts.

The source excerpt is retained verbatim as provenance. LLM-completed wording
is an experimental reformulation, NOT a verified original GSS question.
"""
from __future__ import annotations


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
        attempts = []
        for _ in range(2):
            try:
                kwargs = {"source_incomplete": True} if incomplete else {}
                text = core.llm_craft_survey_question(
                    self.client,
                    item.original_wording,
                    [c.display_label for c in item.choices],
                    self.config.llm_model,
                    **kwargs,
                ).strip()
                # The shared DTAG helper may silently return its input if
                # OpenAI is unavailable. Never present an incomplete excerpt.
                if incomplete and (text == item.original_wording.strip() or
                                   not text.endswith("?") or len(text) < 15):
                    attempts.append({"text": text, "mapper_hit": False,
                                     "rejected": "incomplete_or_unrewritten_source"})
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

    def record(self, text, item, attempts, fallback, reason):
        return {"displayed_wording": text, "question_provenance": {
            "provider": self.backend, "llm_id": self.config.llm_model,
            "prompt_version": self.config.prompt_version, "input_item_id": item.item_id,
            "source_text_incomplete": item.source_text_incomplete,
            "wording_status": ("llm_completion_of_unverified_excerpt"
                               if item.source_text_incomplete and not fallback
                               else "source_or_rephrasing"),
            "attempts": attempts, "mapper_hit": bool(attempts and attempts[-1].get("mapper_hit")),
            "cache_hit": False, "fallback": fallback, "fallback_reason": reason}}
