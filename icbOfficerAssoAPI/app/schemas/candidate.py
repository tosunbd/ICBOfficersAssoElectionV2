"""Pydantic schemas for candidates."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

from app.utils.digits import english_digits_in


class CandidateBase(BaseModel):
    voter_no: str
    name_en: str
    name_bn: str | None = None
    display_order: int = 0

    # "১০১" and "101" are the same voter number: it is stored with English digits
    _digits = field_validator("voter_no", "display_order", mode="before")(english_digits_in)


class CandidateCreate(CandidateBase):
    position_id: int
    election_id: int


class CandidateUpdate(BaseModel):
    voter_no: str | None = None
    name_en: str | None = None
    name_bn: str | None = None
    display_order: int | None = None

    _digits = field_validator("voter_no", "display_order", mode="before")(english_digits_in)


class CandidateResponse(CandidateBase):
    id: int
    position_id: int
    election_id: int
    vote_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateBulkCreate(BaseModel):
    """Create multiple candidates at once."""
    candidates: list[CandidateCreate]
