"""Ballot model — one ballot paper entered by an Election Commissioner."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.time import utcnow


class BallotStatus:
    """Lifecycle of a ballot record (the names are kept from the scanner version,
    so reports and old databases read the same)."""

    PROCESSING = "processing"      # not used by ballot entry
    PROCESSED = "processed"        # entered by an Election Commissioner
    NEEDS_REVIEW = "needs_review"  # not used by ballot entry
    REVIEWED = "reviewed"          # entered, then corrected (shown as "Manual" / corrected in the reports)
    ERROR = "error"                # not used by ballot entry

    COUNTED = (PROCESSED, NEEDS_REVIEW, REVIEWED)
    ALL = (PROCESSING, PROCESSED, NEEDS_REVIEW, REVIEWED, ERROR)


class Ballot(Base):
    __tablename__ = "ballots"
    # one record per ballot paper number: two desks can never enter the same paper
    __table_args__ = (Index("uq_ballots_election_ballot_no", "election_id", "ballot_no", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    election_id: Mapped[int] = mapped_column(Integer, ForeignKey("elections.id"), nullable=False)
    ballot_no: Mapped[int | None] = mapped_column(Integer, nullable=True)          # 1, 2, 3 ... as printed on the paper
    ballot_paper_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # the same, zero-padded: "001"
    pdf_filename: Mapped[str] = mapped_column(String(500), nullable=False)          # label, e.g. "Ballot 001"
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20), default="entry")
    original_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    completed_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preview_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=BallotStatus.PROCESSED)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_warnings: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list: why marks were not counted
    boxes_detected: Mapped[int] = mapped_column(Integer, default=0)        # boxes marked on the paper
    boxes_expected: Mapped[int] = mapped_column(Integer, default=0)        # boxes on the paper
    total_votes_extracted: Mapped[int] = mapped_column(Integer, default=0)  # votes that count
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    printed_paper_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Who entered it, and who last corrected it
    entered_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    entered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    corrected_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)  # SA / Admin who approved the correction
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)          # when it was entered
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # when it was corrected

    # Relationships
    election = relationship("Election", back_populates="ballots")
    votes = relationship("Vote", back_populates="ballot", cascade="all, delete-orphan", lazy="selectin")
