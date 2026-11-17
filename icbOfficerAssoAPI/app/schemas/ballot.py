"""Pydantic schemas for the ballot register (Admin -> Ballots)."""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class VoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ballot_id: int
    candidate_id: int
    position_id: int
    is_valid: bool
    invalid_reason: str | None = None
    confidence_score: float
    created_at: datetime


class BallotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    election_id: int
    ballot_no: int | None = None
    ballot_paper_no: str | None
    pdf_filename: str
    page_number: int = 1
    source: str = "entry"
    status: str
    error_message: str | None
    ocr_warnings: list[str] = []   # why marks were not counted (null votes)
    boxes_detected: int = 0        # boxes marked on the paper
    boxes_expected: int = 0
    total_votes_extracted: int     # votes that count
    is_valid: bool
    entered_by: str | None = None
    corrected_by: str | None = None
    has_preview: bool = False
    scanned_at: datetime
    processed_at: datetime | None
    reviewed_at: datetime | None

    @field_validator("ocr_warnings", mode="before")
    @classmethod
    def _parse_warnings(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return [value]
        return value

    @classmethod
    def from_model(cls, ballot) -> "BallotResponse":
        return cls.model_validate(ballot)


class BallotDetailResponse(BallotResponse):
    votes: list[VoteResponse] = []


class BallotListResponse(BaseModel):
    ballots: list[BallotResponse]
    total: int
    page: int
    per_page: int


class BulkDeleteRequest(BaseModel):
    ballot_ids: list[int] = []
    election_id: int | None = None
    status_filter: str | None = None
    all_matching: bool = False


class BulkDeleteResponse(BaseModel):
    deleted: int
