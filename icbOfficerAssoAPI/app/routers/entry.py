"""Ballot entry router — the form used by the three Election Commissioners.

Every Election Commissioner has a range of ballot paper numbers (EC1 1-150,
EC2 151-300, EC3 301-455).  The papers are entered one by one, in order: the
server tells the form which number is next and accepts only that one, so a
number can neither be skipped nor entered twice, and nobody can enter a paper
outside their own range.  Saving writes the ballot and its votes to the
database in one transaction and the results and reports change at once.

The Super Admin and the Admin can watch: `GET /state` gives the progress of
every desk and, while a commissioner is working, the boxes ticked so far.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Ballot, Election
from app.models.admin_user import AdminUser, Role
from app.models.ballot import BallotStatus
from app.models.election import ElectionStatus
from app.schemas.entry import (
    CorrectionRequest, Desk, DeskDraft, DraftRequest, EntryBallot, EntryElection, EntryRequest, EntryState,
    NullPost, SaveResult,
)
from app.services.ballot_service import ballot_service
from app.services.events import notifier
from app.utils import audit
from app.utils.security import get_current_user, get_ec_user
from app.utils.time import utcnow

router = APIRouter(prefix="/api/entry", tags=["Ballot entry"])

# One save at a time: the "which number is next" check and the insert cannot interleave.
_save_lock = asyncio.Lock()


@dataclass
class _DeskLive:
    """What the server remembers about a desk between requests (not stored in the database)."""

    last_seen: datetime | None = None
    draft: DeskDraft | None = None
    extra: dict = field(default_factory=dict)


_live: dict[str, _DeskLive] = {}


def _desk_live(username: str) -> _DeskLive:
    return _live.setdefault(username.lower(), _DeskLive())


def reset_live_state() -> None:
    """Forget the drafts (the database file was switched / tests)."""
    _live.clear()


# ----------------------------------------------------------------- helpers
async def _active_election(db: AsyncSession) -> Election | None:
    result = await db.execute(
        select(Election).where(Election.status == ElectionStatus.ACTIVE).order_by(Election.id.desc()).limit(1)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def _require_election(db: AsyncSession) -> Election:
    election = await _active_election(db)
    if not election:
        raise HTTPException(status_code=409, detail="No election is active. The Admin must set the election to 'active' before ballots can be entered.")
    return election


def _in_range(user: AdminUser, ballot_no: int) -> bool:
    return user.ballot_from is not None and user.ballot_to is not None and user.ballot_from <= ballot_no <= user.ballot_to


def _range_error(user: AdminUser, ballot_no: int) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail=(f"Ballot {settings.format_ballot_no(ballot_no)} is outside your range. {user.username} enters ballots "
                f"{settings.format_ballot_no(user.ballot_from)} to {settings.format_ballot_no(user.ballot_to)} only."),
    )


def _next_missing(first: int, last: int, entered: set[int]) -> int | None:
    for number in range(first, last + 1):
        if number not in entered:
            return number
    return None


async def _entered(db: AsyncSession, election_id: int) -> dict[int, Ballot]:
    """Every entered ballot of the election by its paper number."""
    result = await db.execute(
        select(Ballot).where(Ballot.election_id == election_id, Ballot.ballot_no.is_not(None))
        .execution_options(populate_existing=True)
    )
    return {b.ballot_no: b for b in result.scalars().all()}


def _desk(user: AdminUser, entered: dict[int, Ballot]) -> Desk:
    mine = {no: b for no, b in entered.items() if _in_range(user, no)}
    next_no = _next_missing(user.ballot_from, user.ballot_to, set(mine))
    live = _desk_live(user.username)
    online = live.last_seen is not None and utcnow() - live.last_seen <= timedelta(seconds=settings.ENTRY_ONLINE_SECONDS)
    last = max(mine.values(), key=lambda b: (b.reviewed_at or b.processed_at or b.scanned_at, b.id), default=None)
    return Desk(
        username=user.username, full_name=user.full_name,
        ballot_from=user.ballot_from, ballot_to=user.ballot_to,
        total=user.ballot_to - user.ballot_from + 1, entered=len(mine),
        next_ballot_no=next_no, next_label=settings.format_ballot_no(next_no) if next_no else None,
        online=online, draft=live.draft if online else None,
        last_ballot_no=last.ballot_no if last else None,
        last_label=settings.format_ballot_no(last.ballot_no) if last else None,
        last_saved_at=(last.reviewed_at or last.processed_at) if last else None,
    )


def _entry_ballot(ballot: Ballot, positions=None) -> EntryBallot:
    marked = [v.candidate_id for v in ballot.votes]
    null_ids = [v.candidate_id for v in ballot.votes if not v.is_valid]
    null_posts: list[NullPost] = []
    if positions:
        per_post: dict[int, int] = {}
        for vote in ballot.votes:
            if not vote.is_valid:
                per_post[vote.position_id] = per_post.get(vote.position_id, 0) + 1
        null_posts = [
            NullPost(position_id=p.id, name_en=p.name_en, name_bn=p.name_bn, marked=per_post[p.id], allowed=p.max_selections)
            for p in positions if p.id in per_post
        ]
    return EntryBallot(
        ballot_id=ballot.id, ballot_no=ballot.ballot_no, label=settings.format_ballot_no(ballot.ballot_no),
        status=ballot.status, entered_by=ballot.entered_by, entered_at=ballot.processed_at or ballot.scanned_at,
        corrected_by=ballot.corrected_by, corrected_at=ballot.reviewed_at,
        candidate_ids=sorted(marked), null_candidate_ids=sorted(null_ids),
        counted=len(marked) - len(null_ids), null_marks=len(null_ids), null_posts=null_posts,
    )


async def _ec_users(db: AsyncSession) -> list[AdminUser]:
    result = await db.execute(
        select(AdminUser).where(AdminUser.role == Role.EC, AdminUser.ballot_from.is_not(None), AdminUser.ballot_to.is_not(None))
        .order_by(AdminUser.ballot_from)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------- state
@router.get("/state", response_model=EntryState)
async def entry_state(db: AsyncSession = Depends(get_db), user: AdminUser = Depends(get_current_user)):
    """Progress of every entry desk.  An Election Commissioner calling this is marked online."""
    if user.is_ec:
        _desk_live(user.username).last_seen = utcnow()
    election = await _active_election(db)
    entered = await _entered(db, election.id) if election else {}
    desks = [_desk(ec, entered) for ec in await _ec_users(db)]
    return EntryState(
        election=EntryElection(
            id=election.id, title=election.title, title_bn=election.title_bn, year=election.year,
            status=election.status, counting_paused=bool(election.counting_paused), total_voters=election.total_voters,
        ) if election else None,
        digits=settings.BALLOT_NUMBER_DIGITS,
        desks=desks,
        me=user.username if user.is_ec and user.ballot_from is not None else None,
        total_entered=sum(d.entered for d in desks),
        total_ballots=sum(d.total for d in desks),
        server_time=utcnow(),
    )


@router.put("/draft", status_code=204)
async def save_draft(data: DraftRequest, user: AdminUser = Depends(get_ec_user)):
    """The boxes ticked so far on the desk's current ballot (kept in memory only, for the monitor)."""
    if not _in_range(user, data.ballot_no):
        raise _range_error(user, data.ballot_no)
    live = _desk_live(user.username)
    live.last_seen = utcnow()
    live.draft = DeskDraft(
        ballot_no=data.ballot_no, label=settings.format_ballot_no(data.ballot_no),
        candidate_ids=sorted(set(data.candidate_ids)), editing=data.editing, updated_at=utcnow(),
    )
    return Response(status_code=204)


# ----------------------------------------------------------------- ballots
@router.get("/ballots", response_model=list[EntryBallot])
async def recent_ballots(
    limit: int = Query(12, ge=1, le=500),
    desk: str | None = Query(None, description="username of an Election Commissioner: only that desk's ballots"),
    db: AsyncSession = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """The latest saved ballots, newest first.  A commissioner sees their own range."""
    election = await _active_election(db)
    if not election:
        return []
    owner = user if user.is_ec else None
    if owner is None and desk:
        owner = next((ec for ec in await _ec_users(db) if ec.username.lower() == desk.lower()), None)
    query = select(Ballot).where(Ballot.election_id == election.id, Ballot.ballot_no.is_not(None))
    if owner is not None:
        query = query.where(Ballot.ballot_no >= owner.ballot_from, Ballot.ballot_no <= owner.ballot_to)
    result = await db.execute(query.order_by(Ballot.ballot_no.desc()).limit(limit))
    positions, _ = await ballot_service.layout(db, election.id)
    return [_entry_ballot(b, positions) for b in result.scalars().all()]


@router.get("/ballots/{ballot_no}", response_model=EntryBallot)
async def get_entry_ballot(ballot_no: int, db: AsyncSession = Depends(get_db), user: AdminUser = Depends(get_current_user)):
    """A saved ballot exactly as entered (a commissioner: only from their own range)."""
    election = await _require_election(db)
    if user.is_ec and not _in_range(user, ballot_no):
        raise _range_error(user, ballot_no)
    ballot = (await _entered(db, election.id)).get(ballot_no)
    if not ballot:
        raise HTTPException(status_code=404, detail=f"Ballot {settings.format_ballot_no(ballot_no)} has not been entered yet")
    positions, _ = await ballot_service.layout(db, election.id)
    return _entry_ballot(ballot, positions)


@router.post("/ballots", response_model=SaveResult, status_code=201)
async def enter_ballot(data: EntryRequest, db: AsyncSession = Depends(get_db), user: AdminUser = Depends(get_ec_user)):
    """Save the next ballot paper of the caller's range and count its votes."""
    label = settings.format_ballot_no(data.ballot_no)
    if not _in_range(user, data.ballot_no):
        raise _range_error(user, data.ballot_no)

    async with _save_lock:
        election = await _require_election(db)
        if election.counting_paused:
            raise HTTPException(status_code=409, detail="Counting is paused by the election commission. Saving is possible again after START.")
        entered = await _entered(db, election.id)
        if data.ballot_no in entered:
            raise HTTPException(status_code=409, detail=f"Ballot {label} is already entered.")
        expected = _next_missing(user.ballot_from, user.ballot_to, set(entered))
        if expected is None:
            raise HTTPException(status_code=409, detail="Every ballot of your range is already entered.")
        if data.ballot_no != expected:
            raise HTTPException(
                status_code=409,
                detail=f"Ballots are entered one by one: the next ballot is {settings.format_ballot_no(expected)}, not {label}.",
            )

        now = utcnow()
        ballot = Ballot(
            election_id=election.id, ballot_no=data.ballot_no, ballot_paper_no=label,
            pdf_filename=f"Ballot {label}", page_number=1, source="entry", status=BallotStatus.PROCESSED,
            entered_by_id=user.id, entered_by=user.username, scanned_at=now, processed_at=now,
        )
        db.add(ballot)
        try:
            await db.flush()
            summary = await ballot_service.store_votes(db, ballot, data.candidate_ids)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail=f"Ballot {label} is already entered.")
        audit.record(
            db, user.id, "ballot_entry",
            f"Ballot {label} entered by {user.username}: {summary['counted']} vote(s) counted"
            + (f", {summary['null_marks']} null mark(s) in {len(summary['null_posts'])} post(s)" if summary["null_marks"] else ""),
        )
        await db.commit()

        live = _desk_live(user.username)
        live.last_seen, live.draft = utcnow(), None
        entered = await _entered(db, election.id)
        positions, _ = await ballot_service.layout(db, election.id)
        result = SaveResult(ballot=_entry_ballot(entered[data.ballot_no], positions), desk=_desk(user, entered))
    notifier.notify()  # results screens and reports follow at once
    return result


@router.put("/ballots/{ballot_no}", response_model=SaveResult)
async def correct_ballot(
    ballot_no: int, data: CorrectionRequest,
    db: AsyncSession = Depends(get_db), user: AdminUser = Depends(get_ec_user),
):
    """Correct a ballot the caller's desk has already saved (a typing mistake): its votes are replaced."""
    label = settings.format_ballot_no(ballot_no)
    if not _in_range(user, ballot_no):
        raise _range_error(user, ballot_no)

    async with _save_lock:
        election = await _require_election(db)
        if election.counting_paused:
            raise HTTPException(status_code=409, detail="Counting is paused by the election commission. Saving is possible again after START.")
        entered = await _entered(db, election.id)
        ballot = entered.get(ballot_no)
        if not ballot:
            raise HTTPException(status_code=404, detail=f"Ballot {label} has not been entered yet")
        before = sorted(v.candidate_id for v in ballot.votes)
        if before == sorted(set(data.candidate_ids)):
            positions, _ = await ballot_service.layout(db, election.id)
            return SaveResult(ballot=_entry_ballot(ballot, positions), desk=_desk(user, entered))  # nothing changed

        try:
            await ballot_service.remove_votes(db, ballot)
            summary = await ballot_service.store_votes(db, ballot, data.candidate_ids)
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc))
        ballot.status = BallotStatus.REVIEWED
        ballot.reviewed_at = utcnow()
        ballot.corrected_by = user.username
        audit.record(
            db, user.id, "ballot_correction",
            f"Ballot {label} corrected by {user.username}: {summary['counted']} vote(s) counted, "
            f"{summary['null_marks']} null mark(s); marked before {json.dumps(before)}, now {json.dumps(sorted(set(data.candidate_ids)))}",
        )
        await db.commit()

        live = _desk_live(user.username)
        live.last_seen, live.draft = utcnow(), None
        entered = await _entered(db, election.id)
        positions, _ = await ballot_service.layout(db, election.id)
        result = SaveResult(ballot=_entry_ballot(entered[ballot_no], positions), desk=_desk(user, entered))
    notifier.notify()
    return result
