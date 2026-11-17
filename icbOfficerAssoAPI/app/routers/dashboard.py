"""Dashboard router — results JSON and the live Server-Sent-Events stream."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.models import Election
from app.models.admin_user import AdminUser
from app.models.election import ElectionStatus
from app.schemas.dashboard import ActiveElectionResponse, DashboardResponse
from app.services.events import notifier
from app.services.vote_counter import vote_counter
from app.utils.security import get_optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/active", response_model=ActiveElectionResponse)
async def get_active_election(db: AsyncSession = Depends(get_db)):
    """The election the public dashboard should show (active, else the newest)."""
    result = await db.execute(
        select(Election).where(Election.status == ElectionStatus.ACTIVE).order_by(Election.id.desc()).limit(1)
    )
    election = result.scalar_one_or_none()
    if not election:
        result = await db.execute(select(Election).order_by(Election.id.desc()).limit(1))
        election = result.scalar_one_or_none()
    if not election:
        raise HTTPException(status_code=404, detail="No election found")
    data = ActiveElectionResponse.model_validate(election, from_attributes=True)
    data.live_display_seconds = election.ballot_display_seconds
    return data


@router.get("/results/{election_id}", response_model=DashboardResponse)
async def get_results(
    election_id: int,
    db: AsyncSession = Depends(get_db),
    user: AdminUser | None = Depends(get_optional_user),
):
    """Current results.  Unpublished results are only returned to the Super Admin and the Admin."""
    try:
        include = True if (user and user.is_admin) else None
        return await vote_counter.get_dashboard_data(db, election_id, include_results=include)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


async def dashboard_events(election_id: int, is_disconnected=None):
    """Async generator behind the SSE endpoint (kept separate so it can be tested).

    Events: `update` (full results, right after every saved ballot and at
    least every SSE_REFRESH_INTERVAL seconds) and `paused`.
    """
    while True:
        if is_disconnected is not None and await is_disconnected():
            return
        seen_version = notifier.version
        try:
            async with AsyncSessionLocal() as db:
                election = (await db.execute(select(Election).where(Election.id == election_id))).scalar_one_or_none()
                if not election:
                    yield {"event": "error", "data": json.dumps({"error": "Election not found"})}
                    return
                if election.dashboard_paused:
                    yield {"event": "paused", "data": json.dumps({"status": "paused"})}
                else:
                    data = await vote_counter.get_dashboard_data(db, election_id)
                    yield {"event": "update", "data": data.model_dump_json()}
        except Exception as exc:
            logger.exception("SSE error")
            yield {"event": "error", "data": json.dumps({"error": str(exc)})}

        await notifier.wait_for_change(seen_version, timeout=settings.SSE_REFRESH_INTERVAL)


@router.get("/stream/{election_id}")
async def stream_results(election_id: int, request: Request):
    """Server-Sent Events: pushes `update` immediately after every change and
    at least every SSE_REFRESH_INTERVAL seconds; `paused` while the admin has
    paused the dashboard."""
    return EventSourceResponse(dashboard_events(election_id, request.is_disconnected), ping=15)
