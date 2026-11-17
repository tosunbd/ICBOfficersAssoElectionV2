"""Ballots router — the register of entered ballots (list, open, delete).

Ballots are created by the Election Commissioners on the entry form
(`routers/entry.py`).  Here the Super Admin and the Admin see all of them; only
the Super Admin can delete one (its number then becomes the next one to enter
for the desk it belongs to).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Ballot
from app.models.admin_user import AdminUser
from app.schemas.ballot import (
    BallotDetailResponse, BallotListResponse, BallotResponse, BulkDeleteRequest, BulkDeleteResponse,
)
from app.services.ballot_service import ballot_service
from app.services.events import notifier
from app.utils import audit
from app.utils.security import get_admin_user, get_superadmin

router = APIRouter(prefix="/api/ballots", tags=["Ballots"])


async def _get_ballot(db: AsyncSession, ballot_id: int) -> Ballot:
    result = await db.execute(select(Ballot).where(Ballot.id == ballot_id))
    ballot = result.scalar_one_or_none()
    if not ballot:
        raise HTTPException(status_code=404, detail="Ballot not found")
    return ballot


# Also at the bare prefix: a 307 slash-redirect through the UI proxy loses the Authorization header.
@router.get("", response_model=BallotListResponse, include_in_schema=False)
@router.get("/", response_model=BallotListResponse)
async def list_ballots(
    election_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=500),
    status_filter: str | None = Query(None, description="processed (entered) | reviewed (corrected)"),
    entered_by: str | None = Query(None, description="username of the Election Commissioner"),
    null_only: bool = Query(False, description="only ballots with null (not counted) marks"),
    ballot_no: int | None = Query(None, description="a single ballot paper number"),
    newest_first: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    filters = [Ballot.election_id == election_id]
    if status_filter:
        filters.append(Ballot.status == status_filter)
    if entered_by:
        filters.append(func.lower(Ballot.entered_by) == entered_by.lower())
    if null_only:
        filters.append(Ballot.boxes_detected > Ballot.total_votes_extracted)
    if ballot_no is not None:
        filters.append(Ballot.ballot_no == ballot_no)

    total = (await db.execute(select(func.count(Ballot.id)).where(*filters))).scalar() or 0
    order = (Ballot.processed_at.desc(), Ballot.id.desc()) if newest_first else (Ballot.ballot_no, Ballot.id)
    result = await db.execute(
        select(Ballot).where(*filters).order_by(*order).offset((page - 1) * per_page).limit(per_page)
    )
    return BallotListResponse(
        ballots=[BallotResponse.from_model(b) for b in result.scalars().all()],
        total=total, page=page, per_page=per_page,
    )


@router.get("/{ballot_id}", response_model=BallotDetailResponse)
async def get_ballot(
    ballot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    return BallotDetailResponse.model_validate(await _get_ballot(db, ballot_id))


@router.delete("/{ballot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ballot(
    ballot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_superadmin),
):
    """Remove a ballot and its votes; the paper has to be entered again by its desk."""
    ballot = await _get_ballot(db, ballot_id)
    await _delete_ballot(db, ballot, current_user)
    await db.commit()
    notifier.notify()


async def _delete_ballot(db: AsyncSession, ballot: Ballot, user: AdminUser) -> None:
    await ballot_service.remove_votes(db, ballot)
    audit.record(
        db, user.id, "ballot_delete",
        f"Ballot {ballot.ballot_paper_no or '#' + str(ballot.id)} (entered by {ballot.entered_by or 'unknown'}) deleted by {user.username}",
    )
    await db.delete(ballot)


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_ballots(
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_superadmin),
):
    """Delete several ballots at once: the given ids, or every ballot of an
    election (optionally only those with one status)."""
    query = select(Ballot)
    if body.ballot_ids:
        query = query.where(Ballot.id.in_(body.ballot_ids))
    elif body.all_matching and body.election_id:
        query = query.where(Ballot.election_id == body.election_id)
        if body.status_filter:
            query = query.where(Ballot.status == body.status_filter)
    else:
        raise HTTPException(status_code=400, detail="Give ballot_ids, or election_id with all_matching=true")

    ballots = (await db.execute(query)).scalars().all()
    for ballot in ballots:
        await _delete_ballot(db, ballot, current_user)
    await db.commit()
    notifier.notify()
    return BulkDeleteResponse(deleted=len(ballots))
