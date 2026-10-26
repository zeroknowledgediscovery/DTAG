"""Neutral study question generation, including incomplete source excerpts.

The source excerpt is retained verbatim as provenance. LLM-completed wording
is an experimental reformulation, NOT a verified original GSS question.
"""
from __future__ import annotations

import re

from .wording_contracts import (
    context_for_native_item, validates_wording, validates_standalone
)
from .grounded_generation import (
    craft_question, validate_complete_choices, has_unresolved_choice_reference,
    source_entry, source_digest,
)


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


class AnswerNeedsClarification(ValueError):
    """Written answer cannot be mapped safely; participant should clarify."""


class AnswerInterpretationUnavailable(RuntimeError):
    """The LLM could not classify an answer; safe to retry unchanged."""


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

    @staticmethod
    def _complete_source_fallback(item, contract, anchored, source, attempts):
        """Show only a validated, self-contained source when LLM rewriting fails.

        This deliberately keeps incomplete map fragments from being presented.
        For audited contracts the participant sees the full restored GSS
        question; for other native items an unchanged source must independently
        pass conservative standalone checks. This is a *visible* provenance
        choice, not an unlogged LLM success.
        """
        if anchored:
            valid = validates_natenviy_form(source) and validates_standalone(source)
            method, reference = "verified_2024_natenviy_source_fallback_v1", NATENVIY_BALLOT_URL
        elif contract:
            valid = validates_standalone(source) and validates_wording(item.item_id, source, contract_override=contract)
            method, reference = "source_grounded_standalone_fallback_v1", contract.source_reference
        else:
            # Dynamic native items carry source_text_incomplete=True even when
            # the GSS map holds a complete standalone question. Reject obvious
            # dependent stems, placeholders and dangling referents before
            # admitting the canonical wording as a last resort.
            valid = bool(
                len(source.strip()) >= 30
                # A complete source may start with a scenario: "Some people
                # think ... Others ... Which ...?" Requiring an interrogative
                # at character 0 silently rejects valid NORC question stems.
                and re.search(
                    r"\b(?:do you|does|did|would you|should|could|will|"
                    r"what|how|why|where|when|which|is it|are you|"
                    r"to what extent|can a|can you)\b",
                    source, re.I,
                )
                and not re.match(
                    r"^(?:if (?:she|he|they)|such|this person|"
                    r"what about|how about|and |or |improving |supporting |"
                    r"the way|its )",
                    source.strip(), re.I,
                )
                and not re.search(
                    r"\b(?:this|such|that)\s+(?:person|book|woman|man)\b",
                    source, re.I,
                )
                and validates_standalone(source)
            )
            method, reference = "native_map_validated_standalone_fallback_v1", None
        if not valid:
            return None
        return {
            "displayed_wording": source.strip(),
            "question_provenance": {
                "provider": "source-validated",
                "llm_id": None,
                "prompt_version": None,
                "item_version": getattr(item, "version", None),
                "input_item_id": item.item_id,
                "source_text_incomplete": item.source_text_incomplete,
                "wording_status": "complete_source_used_after_failed_llm_rewrite",
                "validation_method": method,
                "source_reference": reference,
                "source_standalone_verified": True,
                "fallback": True,
                "fallback_reason": "no_valid_llm_rephrasing_after_two_attempts",
                "generation_attempts": len(attempts),
                "attempts": attempts,
                "mapper_hit": None,
                "cache_hit": False,
            },
        }

    def generate(self, item):
        import dtag_core as core
        from optimizer.dtag_bridge import map_question, RUN_DEFAULTS
        incomplete = item.source_text_incomplete
        # NATENVIY's GSS map label omits its spending stem AND incorrectly
        # borrows NATENVIR's alternate wording. Use the verified 2024 form as
        # the LLM input, retaining the actual model/map label as provenance.
        anchored = verified_natenviy_reference(item)
        contract = context_for_native_item(item.item_id, [c.display_label for c in item.choices])
        source = (NATENVIY_BALLOT_REFERENCE if anchored else
                  contract.source if contract else item.original_wording)
        attempts = []
        native_answers = [c.display_label for c in item.choices]
        mapped_label = item.original_wording
        # Tests and historic mock backends continue through the legacy shared
        # helper; actual OpenAI human-study sessions use the grounded prompt.
        # This has NO effect on optimizer ranking, model geometry, or selection.
        grounded = self.backend == "openai" and hasattr(self.client, "responses")
        retry_feedback = []
        for _ in range(2):
            try:
                if grounded:
                    result = craft_question(
                        self.client, self.config.llm_model, item.item_id,
                        mapped_label, source, native_answers,
                        contract_reference=(contract.source_reference if contract else
                                            NATENVIY_BALLOT_URL if anchored else None),
                        feedback=retry_feedback,
                    )
                    if result["missing_context"]:
                        note = result["missing_details"][:200] or "essential original context unavailable"
                        attempts.append({"rejected": "original_context_unavailable",
                                         "details": note})
                        retry_feedback = [note]
                        continue
                    text = result["question"].strip()
                else:
                    kwargs = {"source_incomplete": True} if incomplete else {}
                    text = core.llm_craft_survey_question(
                        self.client, source, native_answers,
                        self.config.llm_model, **kwargs,
                    ).strip()
                # Shared helper silently returns input on provider failure.
                if (incomplete or self.config.question_mode == "llm_required") and (
                    text == source.strip() or not text.endswith("?") or len(text) < 15
                ):
                    attempts.append({"text": text, "mapper_hit": False,
                                     "rejected": "incomplete_or_unrewritten_source"})
                    retry_feedback = ["Produce a new, complete standalone question; do not return the source fragment."]
                    continue
                if not validates_standalone(text):
                    attempts.append({"text": text, "rejected": "incomplete_standalone_question"})
                    retry_feedback = ["Remove orphaned references or placeholders; provide complete premise and question."]
                    continue
                if contract is not None and not validates_wording(item.item_id, text, contract_override=contract):
                    attempts.append({"text": text, "rejected": "required_referent_or_scale_missing"})
                    retry_feedback = ["Restore all essential source-contract referents and response-scale anchors."]
                    continue
                missing_options = validate_complete_choices(text, source, item.choices)
                if missing_options:
                    attempts.append({"rejected": "response_alternatives_not_displayed",
                                     "missing_options": missing_options[:30]})
                    retry_feedback = [
                        "Your question invokes a list/card or has a many-category response "
                        "scale, but omitted these native alternatives: " +
                        "; ".join(missing_options) + ". Include them all in the displayed question."
                    ]
                    continue
                if has_unresolved_choice_reference(text, source, item.choices):
                    attempts.append({"rejected": "unresolved_choice_or_person_reference"})
                    retry_feedback = [
                        "Do not say 'following', 'these', 'such a person', or "
                        "'the previous question' without making the actual referent/options visible."
                    ]
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

                if self.config.candidate_mode == "native_webapp":
                    # In the actual webapp's "realistic" push mode, crafting
                    # does not force the generated question to map back onto
                    # exactly the target variable. The participant's recorded
                    # response is mapped later through DTAGSession.map_question.
                    return self.record(
                        text, item, attempts, False, None,
                        validation_method=(
                            "gss_2024_grounded_source_and_contract_v2" if grounded and contract else
                            "gss_2024_grounded_source_uncontracted_v2" if grounded else
                            "gss_2024_referent_scale_contract_v1" if contract else
                            "shared_webapp_realistic_craft_no_forced_target_mapping"
                        ),
                        source_reference=contract.source_reference if contract else None,
                    )
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
        fallback = self._complete_source_fallback(
            item, contract, anchored, source, attempts,
        )
        if fallback is not None:
            return fallback
        if incomplete or self.config.question_mode == "llm_required":
            raise QuestionGenerationError(
                "unable to generate a complete, validated question from the source excerpt",
                attempts=attempts,
            )
        return self.record(item.original_wording, item, attempts, True,
                           "mapping ambiguous or provider unavailable")


    def interpret(self, item, displayed_question, free_text):
        """Map a written opinion to an explicitly permitted native category.

        Never infer a synthetic answer, use a lexical fallback, or put the
        participant's prose directly into the native LSM. Ambiguous responses
        are rejected and the participant can clarify without advancing.
        """
        import json
        if self.config.response_mode != "free_text_llm":
            raise ValueError("free-text interpretation is not enabled")
        words = free_text.strip()
        if not words or len(words) > 2000:
            raise ValueError("Please write a response (at most 2000 characters).")
        choices = [c.native_value for c in item.choices]
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["mapped", "ambiguous", "missing"]},
                "native_value": {"type": "string", "enum": choices + [""]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["status", "native_value", "confidence", "reason"],
            "additionalProperties": False,
        }
        prompt = (
            "Classify the respondent's answer to ONE survey question. "
            "The categories are permitted native encodings, not answers to generate. "
            "Use only the participant's stated opinion; do not infer beliefs from context, "
            "demographics, or the distribution of model responses. "
            "Choose 'mapped' ONLY when a category is directly supported and unambiguous. "
            "Choose 'missing' if the respondent explicitly declines or says they cannot answer. "
            "Otherwise choose 'ambiguous' and an empty native_value. "
            "For 'mapped', choose exactly one category string; for other statuses use an empty string. "
            "Return a calibrated confidence in [0,1].\n\n"
            f"QUESTION:\n{displayed_question}\n\n"
            "ALLOWED CATEGORIES:\n" + "\n".join(f"- {v}" for v in choices) +
            f"\n\nRESPONDENT'S WORDS:\n{words}"
        )
        try:
            resp = self.client.responses.create(
                model=self.config.llm_model, input=prompt,
                text={"format": {"type": "json_schema", "name": "human_answer_interpretation_v2",
                                 "schema": schema, "strict": True}},
            )
            from dtag_core import _get_output_text
            outcome = json.loads(_get_output_text(resp))
        except Exception as exc:
            raise AnswerInterpretationUnavailable("answer interpretation unavailable; retry") from exc
        status = outcome.get("status")
        val = outcome.get("native_value")
        confidence = outcome.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise AnswerInterpretationUnavailable("invalid classifier confidence")
        if status == "missing" and val == "":
            if item.required:
                raise AnswerNeedsClarification("This item needs an opinion in your own words.")
            return None, "prefer_not_to_answer", {
                "provider": "openai", "model": self.config.llm_model,
                "status": "missing", "confidence": confidence,
                "reason": outcome.get("reason", ""),
            }
        if (status != "mapped" or val not in choices or
                confidence < self.config.minimum_mapping_confidence):
            raise AnswerNeedsClarification(
                "We could not confidently interpret that response. Please clarify "
                "your view in your own words before continuing."
            )
        return val, None, {
            "provider": "openai", "model": self.config.llm_model,
            "status": "mapped", "confidence": confidence,
            "reason": outcome.get("reason", ""),
        }


    def generate_attention(self, check):
        """LLM-write an instructed-response check, never substitute source text.

        A question does not have to end in '?' to be a valid instructed-response
        check. Validate that the token and an explicit written-answer directive
        survive, and retry malformed outputs before returning a pending error.
        """
        import json
        import re

        schema = {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
            "additionalProperties": False,
        }
        prompt = (
            "Write one SHORT and CLEAR respondent-facing reading/attention check "
            "based on the investigator instruction below. "
            "The response must ask the participant to TYPE or INCLUDE the EXACT "
            "required token in their written answer. "
            "It may be a polite question ending in '?' or a direct imperative "
            "ending in '.'. Do not paraphrase, change or omit the token. "
            "Do not answer the question yourself. "
            "Use neutral wording without unrelated questions.\n\n"
            f"REQUIRED TOKEN: {check.expected_token}\n"
            f"INVESTIGATOR INSTRUCTION: {check.instruction}"
        )
        token_pattern = re.compile(
            r"\b" + re.escape(check.expected_token) + r"\b", re.IGNORECASE
        )
        action_pattern = re.compile(
            r"\b(?:include|write|type|enter|use|reply|respond|provide|insert|"
            r"contain|put)\b", re.IGNORECASE,
        )
        failures = []
        for attempt in range(3):
            try:
                response = self.client.responses.create(
                    model=self.config.llm_model, input=prompt,
                    text={"format": {
                        "type": "json_schema", "name": "human_attention_question_v3",
                        "schema": schema, "strict": True,
                    }},
                )
                from dtag_core import _get_output_text
                obj = json.loads(_get_output_text(response))
                question = str(obj.get("question", "")).strip()
                if (
                    18 <= len(question) <= 500
                    and question != check.instruction.strip()
                    and token_pattern.search(question)
                    and action_pattern.search(question)
                ):
                    return {"displayed_wording": question,
                            "question_provenance": {
                                "provider": self.backend,
                                "llm_id": self.config.llm_model,
                                "prompt_version": self.config.prompt_version,
                                "input_item_id": check.check_id,
                                "fallback": False, "generation_attempts": attempt + 1,
                                "validation_method": "attention_token_and_instruction_preserved_v3",
                            }}
                failures.append({"attempt": attempt + 1, "error": "invalid_generated_instruction"})
            except Exception as exc:
                failures.append({"attempt": attempt + 1, "error": type(exc).__name__})
        raise QuestionGenerationError(
            "unable to generate a valid instructed-response attention question",
            attempts=failures,
        )

    def map_human_response(self, displayed_question, free_text):
        """Use the exact webapp mapping path and its semantic update_state bridge."""
        if self.config.candidate_mode != "native_webapp":
            raise ValueError("shared webapp mapping requires native_webapp mode")
        from .response_mapping import map_human_response
        try:
            return map_human_response(
                self.adapter.world, self.client, self.config.llm_model,
                displayed_question, free_text,
            )
        except Exception as exc:
            raise AnswerInterpretationUnavailable(
                "DTAG webapp mapping unavailable; retry the same written answer"
            ) from exc

    def interpret_multi(self, displayed_question, free_text, allowed_items):
        """Read explicit claims in one written answer into zero or more survey observations.

        Candidate variables are supplied by the reviewed instrument, not invented
        from the respondent's prose. The service independently verifies every
        assignment and resolves conflicts against the committed participant state.
        """
        import json
        if self.config.response_mode != "free_text_multi":
            raise ValueError("multi-variable interpretation is not enabled")
        words = free_text.strip()
        if not words or len(words) > 2000:
            raise ValueError("Please write a response (at most 2000 characters).")
        if not allowed_items:
            raise ValueError("no reviewed mapping candidates")
        candidate_lines = []
        for item in allowed_items:
            values = " | ".join(c.native_value for c in item.choices)
            candidate_lines.append(f"{item.item_id} :: {item.original_wording} :: {values}")
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["mapped", "ambiguous", "missing"]},
                "assignments": {
                    "type": "array", "minItems": 0,
                    "maxItems": self.config.max_response_assignments,
                    "items": {
                        "type": "object",
                        "properties": {
                            "variable": {"type": "string"},
                            "native_value": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["variable", "native_value", "confidence", "evidence"],
                        "additionalProperties": False,
                    },
                },
                "rationale": {"type": "string"},
            },
            "required": ["status", "assignments", "rationale"],
            "additionalProperties": False,
        }
        prompt = (
            "Map this person's ACTUAL WRITTEN RESPONSE to zero or more native GSS "
            "survey categories. This is research measurement, not synthetic persona generation. "
            "One response may state opinions about MULTIPLE survey variables. "
            "The displayed question identifies the primary intended topic, but do not "
            "invent an answer for it if the person did not actually state one. "
            "Make assignments ONLY for clearly expressed views with an unambiguous "
            "native answer from the candidate list. Do not assign categories based on "
            "correlation, ideology, demographics, stereotyping, likelihood, or model predictions. "
            "Do not use weak implications as observations. For each assignment, include "
            "as evidence an EXACT, CONTIGUOUS substring copied from the respondent's text "
            "(not the question). Confidence is in [0,1]. "
            "Output status='mapped' for one or more clear assignments, 'missing' for "
            "explicit refusal or not-knowing, otherwise 'ambiguous'; non-mapped statuses "
            "must have an empty assignments list. Return no more than MAX assignments. "
            f"MAX={self.config.max_response_assignments}\n\n"
            f"DISPLAYED QUESTION:\n{displayed_question}\n\n"
            "ALLOWED GSS VARIABLE :: SOURCE DESCRIPTION :: EXACT NATIVE CATEGORIES:\n"
            + "\n".join(candidate_lines)
            + f"\n\nRESPONDENT'S WORDS:\n{words}"
        )
        try:
            response = self.client.responses.create(
                model=self.config.llm_model, input=prompt,
                text={"format": {"type": "json_schema",
                                 "name": "human_multi_assignments_v3",
                                 "schema": schema, "strict": True}},
            )
            from dtag_core import _get_output_text
            obj = json.loads(_get_output_text(response))
        except Exception as exc:
            raise AnswerInterpretationUnavailable(
                "multi-item answer interpretation unavailable; retry"
            ) from exc
        if not isinstance(obj, dict) or obj.get("status") not in (
            "mapped", "ambiguous", "missing"
        ) or not isinstance(obj.get("assignments"), list):
            raise AnswerInterpretationUnavailable("invalid multi-item classifier result")
        if len(obj["assignments"]) > self.config.max_response_assignments:
            raise AnswerInterpretationUnavailable("classifier exceeded assignment limit")
        if obj["status"] != "mapped" and obj["assignments"]:
            raise AnswerInterpretationUnavailable("inconsistent classifier result")
        return {
            "status": obj["status"],
            "proposed": obj["assignments"],
            "rationale": str(obj.get("rationale", ""))[:1000],
            "provider": "openai",
            "model": self.config.llm_model,
            "mapping_method": "explicit_evidence_only_v3",
        }

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
            "r2_source_context_sha256": source_digest(item.item_id),
            "r2_source_context_available": bool(source_entry(item.item_id)),
            "attempts": attempts,
            "mapper_hit": (None if validation_method in (
                "shared_webapp_realistic_craft_no_forced_target_mapping",
                "gss_2024_referent_scale_contract_v1",
                "gss_2024_grounded_source_and_contract_v2",
                "gss_2024_grounded_source_uncontracted_v2",
            ) else bool(attempts and attempts[-1].get("mapper_hit"))),
            "cache_hit": False, "fallback": fallback, "fallback_reason": reason}}
