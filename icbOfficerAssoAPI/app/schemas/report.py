"""Pydantic schemas for the printable reports (Admin -> Reports)."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.dashboard import DashboardStats


class ReportCandidate(BaseModel):
    candidate_id: int
    voter_no: str
    name_en: str
    name_bn: str | None
    display_order: int            # column order in the ballot tally (as printed on the ballot)
    votes: int
    percentage: float             # of the valid ballots
    rank: int                     # tied candidates share a rank
    outcome: str                  # "elected" | "tie" (shares the last seat) | ""


class ReportPosition(BaseModel):
    position_id: int
    position_order: int
    name_en: str
    name_bn: str | None
    max_selections: int
    total_votes: int
    candidates: list[ReportCandidate]   # by votes, highest first


class ReportBallot(BaseModel):
    ballot_id: int
    serial: int                   # 1, 2, 3 ... in counting order
    ballot_paper_no: str | None
    pdf_filename: str
    page_number: int
    status: str
    is_valid: bool                # False only on ballots voided before whole-ballot rejection was removed
    candidate_ids: list[int]      # the candidates this ballot counts for (the 1s)
    void_marks: int               # marks found but not counted (ballot rules)


class ElectionReport(BaseModel):
    election_id: int
    title: str
    title_bn: str | None
    year: int
    status: str
    total_voters: int
    generated_at: datetime
    stats: DashboardStats
    manual_ballots: int           # selections saved by the Election Commission (status reviewed)
    total_votes: int
    void_marks: int
    positions: list[ReportPosition]
    ballots: list[ReportBallot]
