"""Ballot correction — a change to a saved ballot that waits for approval.

An Election Commissioner who finds a wrong entry does not change the ballot
itself: the corrected ticks are stored here.  Nothing is counted from this
table.  Only when the Super Admin or the Admin approves the request are the
ballot's votes replaced (tables `ballots` / `votes`) and the totals, the
dashboard and the reports updated.  A rejected request changes nothing.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utcnow


class CorrectionStatus:
    PENDING = "pending"      # waiting for the Super Admin / Admin
    APPROVED = "approved"    # applied to the ballot
    REJECTED = "rejected"    # refused: the ballot stays as it was
    WITHDRAWN = "withdrawn"  # taken back by the commissioner before a decision
    ALL = (PENDING, APPROVED, REJECTED, WITHDRAWN)


class BallotCorrection(Base):
    __tablename__ = "ballot_corrections"
    __table_args__ = (Index("ix_ballot_corrections_status", "election_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    election_id: Mapped[int] = mapped_column(Integer, ForeignKey("elections.id"), nullable=False)
    ballot_id: Mapped[int] = mapped_column(Integer, ForeignKey("ballots.id"), nullable=False)
    ballot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_ids: Mapped[str] = mapped_column(Text, nullable=False)           # JSON list: the boxes as they should be
    previous_candidate_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list: the boxes saved at the time of the request
    status: Mapped[str] = mapped_column(String(20), default=CorrectionStatus.PENDING)
    requested_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
