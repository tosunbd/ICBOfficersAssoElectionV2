"""Admin router — dashboard controls, recount, audit log, users, database file."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.config import settings
from app.database import get_db
from app.models import AdminUser, AuditLog, Election
from app.models.election import ElectionStatus
from app.schemas.admin import (
    AuditLogEntry, DatabaseFile, DatabaseInfo, DatabaseYearRequest, SystemStatus, UserAccount,
)
from app.schemas.auth import ResetPasswordRequest
from app.services.ballot_service import ballot_service
from app.services.events import notifier
from app.utils import audit
from app.utils.security import get_admin_user, get_superadmin, hash_password

router = APIRouter(prefix="/api/admin", tags=["Admin"])

APP_VERSION = "2.0.0"


async def _get_election(db: AsyncSession, election_id: int) -> Election:
    result = await db.execute(select(Election).where(Election.id == election_id))
    election = result.scalar_one_or_none()
    if not election:
        raise HTTPException(status_code=404, detail="Election not found")
    return election


@router.put("/dashboard/{election_id}/publish")
async def toggle_dashboard_publish(
    election_id: int,
    publish: bool,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """Show or hide results on the public dashboard."""
    election = await _get_election(db, election_id)
    election.dashboard_published = publish
    audit.record(db, current_user.id, "dashboard_publish" if publish else "dashboard_unpublish",
                 f"Election #{election_id}: dashboard {'published' if publish else 'unpublished'}")
    await db.commit()
    notifier.notify()
    return {"status": "published" if publish else "unpublished", "election_id": election_id}


@router.put("/dashboard/{election_id}/pause")
async def toggle_dashboard_pause(
    election_id: int,
    pause: bool,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """Freeze or resume live updates on the public dashboard."""
    election = await _get_election(db, election_id)
    election.dashboard_paused = pause
    audit.record(db, current_user.id, "dashboard_pause" if pause else "dashboard_resume",
                 f"Election #{election_id}: dashboard {'paused' if pause else 'resumed'}")
    await db.commit()
    notifier.notify()
    return {"status": "paused" if pause else "resumed", "election_id": election_id}


@router.put("/counting/{election_id}/pause")
async def toggle_counting_pause(
    election_id: int,
    pause: bool,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """PAUSE / START the count.  While paused the entry desks cannot save a
    ballot (what is ticked on the form stays there); START lets them carry on."""
    election = await _get_election(db, election_id)
    if election.counting_paused != pause:
        election.counting_paused = pause
        audit.record(db, current_user.id, "counting_pause" if pause else "counting_start",
                     f"Election #{election_id}: ballot entry {'paused' if pause else 'started again'}")
        await db.commit()
        notifier.notify()
    return {"status": "paused" if pause else "running", "election_id": election_id}


@router.put("/election/{election_id}/status")
async def update_election_status(
    election_id: int,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """draft -> active -> completed.  Only ONE election can be active: ballots
    are entered into the active election."""
    if new_status not in ElectionStatus.ALL:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {list(ElectionStatus.ALL)}")
    election = await _get_election(db, election_id)
    old_status = election.status

    if new_status == ElectionStatus.ACTIVE:
        others = (await db.execute(
            select(Election).where(Election.status == ElectionStatus.ACTIVE, Election.id != election_id)
        )).scalars().all()
        for other in others:
            other.status = ElectionStatus.COMPLETED
            audit.record(db, current_user.id, "election_status_change",
                         f"Election #{other.id}: active -> completed (another election was activated)")

    election.status = new_status
    audit.record(db, current_user.id, "election_status_change", f"Election #{election_id}: {old_status} -> {new_status}")
    await db.commit()
    notifier.notify()
    return {"status": new_status, "election_id": election_id}


@router.post("/election/{election_id}/recount")
async def recount_votes(
    election_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    """Rebuild the vote counters from the stored vote records."""
    await _get_election(db, election_id)
    await ballot_service.recount_votes(db, election_id)
    audit.record(db, current_user.id, "vote_recount", f"Election #{election_id}: full recount executed")
    await db.commit()
    return {"status": "recount_complete", "election_id": election_id}


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def get_audit_log(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    result = await db.execute(
        select(AuditLog, AdminUser.username)
        .outerjoin(AdminUser, AuditLog.admin_user_id == AdminUser.id)
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    return [
        AuditLogEntry(
            id=log.id, admin_user_id=log.admin_user_id, username=username,
            action=log.action, details=log.details, created_at=log.created_at,
        )
        for log, username in result.all()
    ]


@router.get("/system", response_model=SystemStatus)
async def system_status(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    active = (await db.execute(
        select(Election.id).where(Election.status == ElectionStatus.ACTIVE).order_by(Election.id.desc()).limit(1)
    )).scalar_one_or_none()
    users = (await db.execute(select(func.count(AdminUser.id)))).scalar() or 0
    path = settings.database_file
    return SystemStatus(
        version=APP_VERSION,
        active_election_id=active,
        database_file=str(path) if path else None,
        entry_ranges={
            name: f"{settings.format_ballot_no(first)}-{settings.format_ballot_no(last)}"
            for name, (first, last) in settings.entry_ranges.items()
        },
        ballot_number_digits=settings.BALLOT_NUMBER_DIGITS,
        total_users=users,
    )


# ---------------------------------------------------------------------------
# User accounts (SA, Admin, EC1, EC2, EC3)
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserAccount])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_admin_user),
):
    users = (await db.execute(select(AdminUser).order_by(AdminUser.id))).scalars().all()
    logins = dict((await db.execute(
        select(AuditLog.admin_user_id, func.max(AuditLog.created_at)).where(AuditLog.action == "login")
        .group_by(AuditLog.admin_user_id)
    )).all())
    return [
        UserAccount(
            id=u.id, username=u.username, full_name=u.full_name, role=u.role,
            ballot_from=u.ballot_from, ballot_to=u.ballot_to, last_login_at=logins.get(u.id),
        )
        for u in users
    ]


@router.put("/users/{user_id}/password")
async def reset_user_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_superadmin),
):
    """The Super Admin sets a new password for any account (e.g. a forgotten one)."""
    user = (await db.execute(select(AdminUser).where(AdminUser.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    audit.record(db, current_user.id, "password_reset", f"Password of {user.username} reset by {current_user.username}")
    await db.commit()
    return {"status": "ok", "username": user.username}


# ---------------------------------------------------------------------------
# Database file per election year (icbOfficerAssoDB{Year}.db)
# ---------------------------------------------------------------------------

def _year_files() -> list[DatabaseFile]:
    """The other icbOfficerAssoDB<year>.db files in the database folder."""
    template = settings.sqlite_file(settings._resolve_sqlite_url(settings.DATABASE_URL))
    if template is None or not settings.database_url_has_year:
        return []
    head, _, tail = re.split(r"(\{year\})", template.name, maxsplit=1, flags=re.IGNORECASE)
    pattern = re.compile(rf"^{re.escape(head)}(\d{{4}}){re.escape(tail)}$", re.IGNORECASE)
    files = []
    for path in template.parent.glob("*"):
        match = pattern.match(path.name)
        if match and path.is_file():
            stat = path.stat()
            year = int(match.group(1))
            files.append(DatabaseFile(
                year=year, file_name=path.name, size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime), current=year == settings.database_year,
            ))
    return sorted(files, key=lambda f: f.year, reverse=True)


def _database_info() -> DatabaseInfo:
    path = settings.database_file
    exists = path is not None and path.exists()
    return DatabaseInfo(
        year=settings.database_year,
        per_year=settings.database_url_has_year,
        file_name=path.name if path else None,
        path=str(path) if path else None,
        size_bytes=path.stat().st_size if exists else None,
        files=_year_files(),
    )


@router.get("/database", response_model=DatabaseInfo)
async def database_info(current_user: AdminUser = Depends(get_admin_user)):
    return _database_info()


@router.put("/database", response_model=DatabaseInfo)
async def switch_database_year(
    body: DatabaseYearRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_superadmin),
):
    """Use the database file of another election year (created empty if it does not exist).

    The user accounts are copied into a new file so the same logins keep working."""
    from app.routers.entry import reset_live_state

    if not settings.database_url_has_year:
        raise HTTPException(status_code=400, detail="DATABASE_URL in .env has no {Year} placeholder, so the year cannot be changed here")
    old_year = settings.database_year
    if body.year == old_year:
        return _database_info()

    users = (await db.execute(select(AdminUser))).scalars().all()
    accounts = [(u.username, u.password_hash, u.full_name, u.role, u.ballot_from, u.ballot_to) for u in users]
    audit.record(db, current_user.id, "database_switch", f"Database year {old_year} -> {body.year}")
    await db.commit()

    await database.switch_database(settings.database_url_for(body.year))
    settings.save_database_year(body.year)
    reset_live_state()

    async with database.AsyncSessionLocal() as new_db:
        known = {name.lower() for name in (await new_db.execute(select(AdminUser.username))).scalars().all()}
        for username, password_hash, full_name, role, ballot_from, ballot_to in accounts:
            if username.lower() not in known:
                new_db.add(AdminUser(
                    username=username, password_hash=password_hash, full_name=full_name, role=role,
                    ballot_from=ballot_from, ballot_to=ballot_to,
                ))
        await new_db.flush()
        user_id = (await new_db.execute(
            select(AdminUser.id).where(AdminUser.username == current_user.username)
        )).scalar_one_or_none()
        audit.record(new_db, user_id, "database_switch", f"Database year {old_year} -> {body.year}")
        await new_db.commit()
    notifier.notify()
    return _database_info()

