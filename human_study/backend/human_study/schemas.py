from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Start(Input):
    # Reserved fields are deliberately not accepted yet. PID is never authentication.
    pass


class Consent(Input):
    accepted: bool
    expected_session_version: int = Field(ge=0)


class Answer(Input):
    question_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    answer_value: str | None = Field(default=None, max_length=200)
    missing_reason: Literal["skip", "prefer_not_to_answer"] | None = None
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    expected_session_version: int = Field(ge=0)
