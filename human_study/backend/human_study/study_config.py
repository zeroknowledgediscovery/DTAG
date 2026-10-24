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


class StudyConfig(StrictModel):
    schema_version: str = "1"
    study_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=60)
    model_key: Literal["gss/gss_2024"] = "gss/gss_2024"
    model_release: str = "v0.2.1"
    reviewed: bool = False
    consent_version: str = "pilot-draft-1"
    consent_text: str = "This internal pilot asks categorical survey questions. Participation is voluntary. You may stop at any time. Answers are stored for research. This receipt is not a payment code."
    intervention_steps: int = Field(default=20, ge=1, le=40)
    llm_model: str = "gpt-4.1-mini-2025-04-14"
    prompt_version: str = "dtag-human-survey-question-v2-excerpt"
    excluded_ids: tuple[str, ...] = ()
    ethics_disallowed_ids: tuple[str, ...] = ()
    items: tuple[Item, ...] = Field(min_length=3, max_length=100)

    @model_validator(mode="after")
    def unique_instrument(self):
        ids = [i.item_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("baseline/intervention/outcome/control item sets must be disjoint")
        for phase in ("baseline", "intervention", "outcome"):
            if not self.bank(phase):
                raise ValueError(f"missing {phase} bank")
        for item in self.items:
            vals = [c.native_value for c in item.choices]
            if len(vals) != len(set(vals)):
                raise ValueError(f"duplicate choices: {item.item_id}")
        return self

    def bank(self, phase: str) -> list[Item]:
        return [i for i in self.items if i.phase == phase]

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
