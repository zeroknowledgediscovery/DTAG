from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PROLIFIC_ID = r"^[A-Za-z0-9]{1,64}$"


class Start(Input):
    # Prolific URL parameters (PROLIFIC_PID, STUDY_ID, SESSION_ID). Linkage only;
    # a PID is never treated as a credential for anything beyond resuming its session.
    prolific_pid: str | None = Field(default=None, pattern=PROLIFIC_ID)
    prolific_study_id: str | None = Field(default=None, pattern=PROLIFIC_ID)
    prolific_session_id: str | None = Field(default=None, pattern=PROLIFIC_ID)


class Restart(Input):
    """Empty body: a new test session cannot supply Prolific identifiers."""
    pass


class Consent(Input):
    accepted: bool
    expected_session_version: int = Field(ge=0)


class Answer(Input):
    question_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    answer_value: str | None = Field(default=None, max_length=200)
    # V2: preserve respondent's own words, never pass them as a native state.
    text_answer: str | None = Field(default=None, max_length=2000)
    missing_reason: Literal["skip", "prefer_not_to_answer"] | None = None
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    expected_session_version: int = Field(ge=0)
