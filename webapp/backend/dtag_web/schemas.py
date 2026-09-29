"""Request/response schemas for the DTAG Web API.

Browser-supplied profile fields are whitelisted here: no paths, commands,
modules or URLs are accepted. Model/map keys are validated by the engine
against the catalog and the repository map inventory.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    persona: Optional[str] = Field(None, max_length=4000)
    country: Optional[str] = Field(None, max_length=120)
    continent: Optional[str] = Field(None, max_length=120)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    za: Optional[str] = Field(None, pattern=r"^(?i:ZA)?\d{1,5}$")
    model_key: Optional[str] = Field(None, pattern=r"^[a-z]+/[A-Za-z0-9._-]+$", max_length=120)
    map_key: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_./-]+\.csv$", max_length=200)
    ideology: Optional[bool] = None
    polar_set: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]+$", max_length=64)
    semantic_fallback: Optional[Literal["off", "answer_only", "update_state"]] = None
    resp_mode: Optional[Literal["max", "draw"]] = None
    semantic_resp_mode: Optional[Literal["max", "draw"]] = None
    seed: Optional[int] = Field(None, ge=0, le=2**31 - 1)
    k: Optional[int] = Field(None, ge=1, le=200)
    prefilter: Optional[int] = Field(None, ge=1, le=2000)
    min_map_score: Optional[float] = Field(None, ge=0, le=20)
    semantic_k: Optional[int] = Field(None, ge=1, le=50)
    semantic_prefilter: Optional[int] = Field(None, ge=1, le=500)
    semantic_min_confidence: Optional[float] = Field(None, ge=0, le=1)
    max_assign: Optional[int] = Field(None, ge=0, le=200)
    assign_prefilter: Optional[int] = Field(None, ge=1, le=5000)
    state_keep: Optional[int] = Field(None, ge=1, le=5000)

    def cleaned(self) -> Dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    profile: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    model_key: Optional[str] = Field(None, pattern=r"^[a-z]+/[A-Za-z0-9._-]+$", max_length=120)
    overrides: Overrides = Field(default_factory=Overrides)
    install_if_missing: bool = True


class ProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    description: Optional[str] = Field(None, max_length=500)
    base_profile: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    model_key: Optional[str] = Field(None, pattern=r"^[a-z]+/[A-Za-z0-9._-]+$", max_length=120)
    overrides: Overrides = Field(default_factory=Overrides)


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    question: str = Field(..., min_length=1, max_length=2000)


class Health(BaseModel):
    status: str
    dtag_version: str
    native_runtime: str
    openai_configured: bool
    llm_backend: str
    model_release: str
    model_cache_root: str
    models_loaded: int
    sessions: int


class Anchor(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    variable: str
    survey_question: str
    response: str
    distribution: Dict[str, float]
    map_provenance: Optional[Dict[str, str]] = None


class Mapping(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    type: str
    label: str
    semantic_trigger: Optional[str] = None
    state_updated: bool
    semantic_fallback_mode: str


class IdeologyStep(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    enabled: bool
    before: Optional[float] = None
    after: Optional[float] = None
    delta: Optional[float] = None


class QuestionResult(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    query_idx: int
    question: str
    answer: str
    selected_variables: List[str]
    anchors: List[Anchor]
    selection_rationale: str
    mapping: Mapping
    state_updates: Dict[str, str]
    state_changed: bool
    geographic_conditioning: Dict[str, Any]
    temporal_conditioning: Dict[str, Any]
    ideology: IdeologyStep
    timings: Dict[str, float]


class SessionOut(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    session_id: str
    resolved_profile: Dict[str, Any]
    model: Dict[str, Any]
    initial_state: Dict[str, str]
    current_state: Dict[str, str]
    geographic_conditioning: Dict[str, Any]
    temporal_conditioning: Dict[str, Any]
    ideology: Dict[str, Any]


class RecommendIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    persona: str = Field("", max_length=4000)
    country: str = Field("", max_length=120)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    preferred_model: Optional[str] = Field(None, pattern=r"^[a-z]+/[A-Za-z0-9._-]+$", max_length=120)
