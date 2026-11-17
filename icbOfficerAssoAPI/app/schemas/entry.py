"""Pydantic schemas for ballot entry (the form used by EC1, EC2 and EC3)."""

from datetime import datetime

from pydantic import BaseModel, Field


class EntryRequest(BaseModel):
    """The boxes marked on one ballot paper (several per post are allowed: the rules decide what counts)."""

    ballot_no: int = Field(ge=1)
    candidate_ids: list[int] = Field(default_factory=list, max_length=500)


class CorrectionRequest(BaseModel):
    candidate_ids: list[int] = Field(default_factory=list, max_length=500)


class DraftRequest(BaseModel):
    """What a desk has ticked so far, shown live to the Super Admin and the Admin."""

    ballot_no: int = Field(ge=1)
    candidate_ids: list[int] = Field(default_factory=list, max_length=500)
    editing: bool = False  # correcting a saved ballot rather than entering the next one


class NullPost(BaseModel):
    position_id: int
    name_en: str
    name_bn: str | None
    marked: int
    allowed: int


class Correction(BaseModel):
    """A change to a saved ballot, kept apart until the Super Admin or the Admin decides on it."""

    id: int
    ballot_id: int
    ballot_no: int
    label: str
    status: str                        # pending | approved | rejected | withdrawn
    requested_by: str
    requested_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    candidate_ids: list[int]           # the boxes as they should be
    previous_candidate_ids: list[int]  # the boxes saved when the request was made
    counted: int                       # votes that would count after the correction
    null_marks: int
    previous_counted: int
    previous_null_marks: int


class EntryBallot(BaseModel):
    """One saved ballot exactly as entered."""

    ballot_id: int
    ballot_no: int
    label: str                       # "001"
    status: str                      # processed (entered) | reviewed (corrected)
    entered_by: str | None
    entered_at: datetime | None
    corrected_by: str | None
    corrected_at: datetime | None
    approved_by: str | None = None
    candidate_ids: list[int]         # every box marked on the paper
    null_candidate_ids: list[int]    # marked, but not counted (null vote)
    counted: int                     # votes that count
    null_marks: int
    null_posts: list[NullPost]
    pending: Correction | None = None  # a correction of this ballot is waiting for approval


class DeskDraft(BaseModel):
    ballot_no: int
    label: str
    candidate_ids: list[int]
    editing: bool
    updated_at: datetime


class Desk(BaseModel):
    """One Election Commissioner's entry desk and how far it has got."""

    username: str
    full_name: str | None
    ballot_from: int
    ballot_to: int
    total: int                       # papers in the range
    entered: int
    next_ballot_no: int | None       # None = the whole range is entered
    next_label: str | None
    online: bool
    draft: DeskDraft | None          # the ballot on the desk right now (only while online)
    last_ballot_no: int | None
    last_label: str | None
    last_saved_at: datetime | None
    pending_corrections: int = 0     # corrections of this desk waiting for approval


class EntryElection(BaseModel):
    id: int
    title: str
    title_bn: str | None
    year: int
    status: str
    counting_paused: bool
    total_voters: int


class EntryState(BaseModel):
    election: EntryElection | None   # None = no active election: nothing can be entered
    digits: int
    desks: list[Desk]
    me: str | None                   # the caller's desk (username) when the caller is an Election Commissioner
    total_entered: int
    total_ballots: int               # papers in all ranges together
    pending_corrections: int = 0     # corrections waiting for the Super Admin / Admin
    server_time: datetime


class SaveResult(BaseModel):
    ballot: EntryBallot
    desk: Desk


class DecisionResult(BaseModel):
    correction: Correction
    ballot: EntryBallot
