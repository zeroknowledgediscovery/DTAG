"""Existing neutral question generation and one-item mapping, with bounded fallback."""
from __future__ import annotations


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
        attempts = []
        for _ in range(2):
            try:
                text = core.llm_craft_survey_question(self.client, item.original_wording,
                         [c.display_label for c in item.choices], self.config.llm_model)
                mapping = map_question(self.adapter.world, self.client, text, self.config.llm_model,
                                       {**RUN_DEFAULTS, "k": 1})
                hit = mapping["variables"] == [item.item_id]
                attempts.append({"text": text, "mapped_ids": mapping["variables"], "mapper_hit": hit,
                                 "canonical_returned": text == item.original_wording})
                if hit:
                    return self.record(text, item, attempts, text == item.original_wording,
                                       "canonical wording returned by core (provider may have fallen back)"
                                       if text == item.original_wording else None)
            except Exception as e:
                attempts.append({"error": type(e).__name__})
        return self.record(item.original_wording, item, attempts, True, "mapping ambiguous or provider unavailable")

    def record(self, text, item, attempts, fallback, reason):
        return {"displayed_wording": text, "question_provenance": {
            "provider": self.backend, "llm_id": self.config.llm_model,
            "prompt_version": self.config.prompt_version, "input_item_id": item.item_id,
            "attempts": attempts, "mapper_hit": bool(attempts and attempts[-1].get("mapper_hit")),
            "cache_hit": False, "fallback": fallback, "fallback_reason": reason}}
