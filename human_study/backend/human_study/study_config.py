"""Versioned instrument contracts. Examples require investigator review."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Choice(StrictModel):
    native_value: str = Field(min_length=1, max_length=200)
    display_label: str = Field(min_length=1, max_length=300)


class Item(StrictModel):
    item_id: str = Field(pattern=r"^[A-Za-z0-9_]+$", max_length=80)
    original_wording: str = Field(min_length=4, max_length=5000)
    # Preserve incomplete source text; allow LLM to create a labeled, non-verbatim question.
    source_text_incomplete: bool = False
    choices: tuple[Choice, ...] = Field(min_length=2, max_length=20)
    phase: Literal["baseline", "intervention", "outcome", "control"]
    required: bool = True
    version: str = "1"


class AttentionCheck(StrictModel):
    check_id: str = Field(pattern=r"^attention_[A-Za-z0-9_]+$", max_length=80)
    # instructed_token: "include the exact word X" (LLM-rendered by default).
    # factual: an obvious-answer question shown verbatim; passes when the reply
    # contains any accepted answer as a whole word or phrase.
    kind: Literal["instructed_token", "factual"] = "instructed_token"
    instruction: str = Field(min_length=10, max_length=500)
    expected_token: str | None = Field(default=None, pattern=r"^[A-Za-z]{3,20}$")
    accepted_answers: tuple[str, ...] = Field(default=(), max_length=20)
    # llm: model writes participant-facing wording; verbatim: show instruction as is.
    render: Literal["llm", "verbatim"] = "llm"
    # Show after this many substantive answers. None = after all substantive answers.
    after_substantive: int | None = Field(default=None, ge=0, le=100)
    version: str = "1"

    @model_validator(mode="after")
    def scoring_rule(self):
        if self.kind == "instructed_token":
            if not self.expected_token:
                raise ValueError("instructed_token attention checks require expected_token")
            if self.render == "verbatim" and not self.passes(self.instruction):
                raise ValueError("verbatim instructed_token checks must show the expected token")
        if self.kind == "factual":
            if not self.accepted_answers or self.expected_token:
                raise ValueError("factual attention checks use accepted_answers, not expected_token")
            if self.render != "verbatim":
                raise ValueError("factual attention checks are displayed verbatim")
            if any(not 1 <= len(a.strip()) <= 60 for a in self.accepted_answers):
                raise ValueError("accepted answers must be 1-60 characters")
        return self

    def passes(self, text: str) -> bool:
        import re
        answers = (self.expected_token,) if self.kind == "instructed_token" else self.accepted_answers
        return any(re.search(r"(?<!\w)" + re.escape(a.strip()) + r"(?!\w)", text, flags=re.IGNORECASE)
                   for a in answers)


class ProlificSettings(StrictModel):
    """Prolific linkage and completion codes. Codes are configured in Prolific."""
    # Reject sessions opened without PROLIFIC_PID (outside local mode).
    required: bool = True
    completion_url: str = Field(default="https://app.prolific.com/submissions/complete",
                                pattern=r"^https://[^\s?#]+$")
    # Shown to participants who fail fewer than attention_fail_threshold checks.
    completion_code: str = Field(pattern=r"^[A-Za-z0-9]{4,32}$")
    # Shown when failures >= threshold; configure as "manual review" in Prolific.
    # None: everyone receives completion_code (failures are still archived).
    review_code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{4,32}$")
    # Prolific "No consent" path: configure it to REQUEST A RETURN, never approval.
    # Optional for legacy study configs; required for the new Prolific instrument.
    no_consent_code: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{4,32}$")
    attention_fail_threshold: int = Field(default=2, ge=1, le=100)
    # Recorded with each reward record, e.g. "GBP 2.50"; informational only.
    reward: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def distinct_codes(self):
        codes = [code for code in (
            self.completion_code, self.review_code, self.no_consent_code
        ) if code is not None]
        if len(codes) != len(set(codes)):
            raise ValueError("completion_code, review_code and no_consent_code must be distinct")
        return self


class QualitySettings(StrictModel):
    """Per-answer review flags. Recorded only; they never change the code shown."""
    fast_seconds: float = Field(default=4.0, ge=0, le=600)
    short_words: int = Field(default=3, ge=0, le=100)
    duplicate_similarity: float = Field(default=0.9, ge=0.5, le=1.0)


class StudyConfig(StrictModel):
    schema_version: str = "1"
    study_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=60)
    model_key: Literal["gss/gss_2024"] = "gss/gss_2024"
    model_release: str = "v0.2.1"
    reviewed: bool = False
    consent_version: str = "pilot-draft-1"
    consent_text: str = "This internal pilot asks categorical survey questions. Participation is voluntary. You may stop at any time. Answers are stored for research. This receipt is not a payment code."
    initial_steps: int | None = Field(default=None, ge=1, le=40)
    intervention_steps: int = Field(default=20, ge=1, le=40)
    # V2: generated questions; free-text answers classified to native categories.
    question_mode: Literal["legacy", "llm_required"] = "legacy"
    response_mode: Literal["click", "free_text_llm", "free_text_multi"] = "click"
    max_response_assignments: int = Field(default=5, ge=1, le=200)
    # Native mode delegates the candidate universe/geometry to the exact webapp
    # optimizer/session_push.py path. Instrument mode preserves historic pilots.
    candidate_mode: Literal["instrument", "native_webapp"] = "instrument"
    # Webapp resp_mode=max ranks modal shifts; draw ranks expected shifts.
    push_response_mode: Literal["max", "draw"] = "max"
    # Non-geometric, investigator-designed attention checks (V3).
    attention_checks: tuple[AttentionCheck, ...] = ()
    prolific: ProlificSettings | None = None
    quality: QualitySettings = QualitySettings()
    minimum_mapping_confidence: float = Field(default=0.80, ge=0.5, le=1.0)
    llm_model: str = "gpt-4.1-mini-2025-04-14"
    prompt_version: str = "dtag-human-survey-question-v2-excerpt"
    excluded_ids: tuple[str, ...] = ()
    ethics_disallowed_ids: tuple[str, ...] = ()
    items: tuple[Item, ...] = Field(min_length=3, max_length=100)

    @model_validator(mode="after")
    def unique_instrument(self):
        ids = [i.item_id for i in self.items]
        control_ids = [c.check_id for c in self.attention_checks]
        if len(control_ids) != len(set(control_ids)) or set(control_ids) & set(ids):
            raise ValueError("attention checks must have unique non-model identifiers")
        if self.attention_checks and self.response_mode != "free_text_multi":
            raise ValueError("attention checks require V3 free_text_multi mode")
        last_position = -1
        for check in self.attention_checks:
            position = self.attention_position(check)
            if not 0 <= position <= len(self.bank("baseline")) + self.intervention_steps:
                raise ValueError("attention placement outside substantive-question sequence")
            if position < last_position:
                raise ValueError("attention checks must be sorted by after_substantive")
            last_position = position
        if self.initial_steps is not None and self.initial_steps > sum(
            i.phase == "baseline" for i in self.items
        ):
            raise ValueError("initial_steps exceeds the initial question bank")
        if len(ids) != len(set(ids)):
            raise ValueError("baseline/intervention/outcome/control item sets must be disjoint")
        for phase in ("baseline", "intervention"):
            if not self.bank(phase) and (phase != "intervention" or self.candidate_mode != "native_webapp"):
                raise ValueError(f"missing {phase} bank")
        if self.candidate_mode == "native_webapp" and self.response_mode != "free_text_multi":
            raise ValueError("native_webapp selection requires V3 free-text multi mapping")
        if self.response_mode == "click" and not self.bank("outcome"):
            raise ValueError("legacy study requires outcome questions")
        if self.response_mode in ("free_text_llm", "free_text_multi"):
            if self.question_mode != "llm_required":
                raise ValueError("free-text V2 requires LLM-generated questions")
            if not 1 <= len(self.bank("baseline")) <= 40:
                raise ValueError("V2 requires 1–40 initial questions")
            if (self.candidate_mode == "instrument" and
                    len(self.bank("intervention")) < self.intervention_steps):
                raise ValueError("instrument-limited intervention bank is smaller than planned sequence")
        for item in self.items:
            vals = [c.native_value for c in item.choices]
            if len(vals) != len(set(vals)):
                raise ValueError(f"duplicate choices: {item.item_id}")
        return self

    def attention_position(self, check: AttentionCheck) -> int:
        return (len(self.bank("baseline")) + self.intervention_steps
                if check.after_substantive is None else check.after_substantive)

    def bank(self, phase: str) -> list[Item]:
        items = [i for i in self.items if i.phase == phase]
        return items[:self.initial_steps] if phase == "baseline" and self.initial_steps is not None else items

    def item(self, item_id: str) -> Item:
        found = next((i for i in self.items if i.item_id == item_id), None)
        if found is None:
            raise ValueError("unknown instrument item")
        return found

    @property
    def config_hash(self) -> str:
        return digest(self.model_dump(mode="json"))

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))
