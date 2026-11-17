"""Elections router — elections and their positions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Election, Position
from app.models.admin_user import AdminUser
from app.models.election import ElectionStatus
from app.schemas.election import (
    ElectionCreate, ElectionDetailResponse, ElectionResponse, ElectionUpdate,
    PositionCreate, PositionResponse, PositionUpdate,
)
from app.services.events import notifier
from app.utils import audit
from app.utils.security import get_admin_user, get_superadmin

router = APIRouter(prefix="/api/elections", tags=["Elections"])

async def _get_election(db: AsyncSession, election_id: int) -> Election:
    result = await db.execute(select(Election).where(Election.id == election_id))
    election = result.scalar_one_or_none()
    if not election:
        raise HTTPException(status_code=404, detail="Election not found")
    return election


# Also at the bare prefix: a 307 slash-redirect through the UI proxy loses the Authorization header.
@router.get("", response_model=list[ElectionResponse], include_in_schema=False)
@router.get("/", response_model=list[ElectionResponse])
async def list_elections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Election).order_by(Election.year.desc(), Election.id.desc()))
    return result.scalars().all()


@router.get("/{election_id}", response_model=ElectionDetailResponse)
async def get_election(election_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_election(db, election_id)


# Also at the bare prefix: a 307 slash-redirect through the UI proxy loses the Authorization header.
@router.post("", response_model=ElectionResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/", response_model=ElectionResponse, status_code=status.HTTP_201_CREATED)
async def create_election(
    data: ElectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    election = Election(**data.model_dump())
    db.add(election)
    await db.flush()
    audit.record(db, current_user.id, "election_create", f"Election #{election.id} '{election.title}' created")
    await db.commit()
    await db.refresh(election)
    return election


@router.put("/{election_id}", response_model=ElectionResponse)
async def update_election(
    election_id: int,
    data: ElectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    election = await _get_election(db, election_id)
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in ElectionStatus.ALL:
        raise HTTPException(status_code=400, detail=f"status must be one of {list(ElectionStatus.ALL)}")
    for key, value in changes.items():
        setattr(election, key, value)
    audit.record(db, current_user.id, "election_update", f"Election #{election_id}: {changes}")
    await db.commit()
    await db.refresh(election)
    notifier.notify()
    return election


@router.delete("/{election_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_election(
    election_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_superadmin),
):
    election = await _get_election(db, election_id)
    audit.record(db, current_user.id, "election_delete", f"Election #{election_id} '{election.title}' deleted")
    await db.delete(election)
    await db.commit()
    notifier.notify()


# --- Positions ------------------------------------------------------------
@router.post("/{election_id}/seed-positions", response_model=ElectionDetailResponse)
async def seed_default_positions(
    election_id: int,
    with_template_candidates: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """Create the 13 standard ICB positions (optionally with the 30 candidates
    printed on the 2026 ballot paper)."""
    from app.seed import DEFAULT_POSITIONS, add_ballot_2026

    election = await _get_election(db, election_id)
    if election.positions:
        raise HTTPException(status_code=400, detail="Positions already exist for this election")

    if with_template_candidates:
        await add_ballot_2026(db, election_id)
    else:
        for order, (name_en, name_bn, seats) in enumerate(DEFAULT_POSITIONS, start=1):
            db.add(Position(election_id=election_id, position_order=order, name_en=name_en, name_bn=name_bn, max_selections=seats))

    audit.record(
        db, current_user.id, "positions_seed",
        f"Election #{election_id}: default positions seeded" + (" with the 2026 ballot candidates" if with_template_candidates else ""),
    )
    await db.commit()
    db.expire_all()
    return await _get_election(db, election_id)


@router.post("/{election_id}/positions", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def add_position(
    election_id: int,
    data: PositionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    await _get_election(db, election_id)
    position = Position(election_id=election_id, **data.model_dump())
    db.add(position)
    audit.record(db, current_user.id, "position_create", f"Election #{election_id}: position '{data.name_en}' added")
    await db.commit()
    await db.refresh(position)
    return position


@router.put("/{election_id}/positions/{position_id}", response_model=PositionResponse)
async def update_position(
    election_id: int,
    position_id: int,
    data: PositionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.election_id == election_id)
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    changes = data.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(position, key, value)
    audit.record(db, current_user.id, "position_update", f"Position #{position_id}: {changes}")
    await db.commit()
    await db.refresh(position)
    notifier.notify()
    return position


@router.delete("/{election_id}/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    election_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.election_id == election_id)
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    audit.record(db, current_user.id, "position_delete", f"Position #{position_id} '{position.name_en}' deleted")
    await db.delete(position)
    await db.commit()
    notifier.notify()
