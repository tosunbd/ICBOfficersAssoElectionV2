"""Pydantic schemas for admin endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    id: int
    admin_user_id: int | None
    username: str | None
    action: str
    details: str | None
    created_at: datetime | None


class SystemStatus(BaseModel):
    version: str
    active_election_id: int | None
    database_file: str | None
    entry_ranges: dict[str, str]   # {"EC1": "001-150", ...}
    ballot_number_digits: int
    total_users: int


class UserAccount(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str
    ballot_from: int | None
    ballot_to: int | None
    last_login_at: datetime | None = None


class DatabaseFile(BaseModel):
    year: int
    file_name: str
    size_bytes: int
    modified_at: datetime
    current: bool


class DatabaseInfo(BaseModel):
    """The database file in use and the other per-year files next to it."""
    year: int
    per_year: bool              # DATABASE_URL contains {Year}
    file_name: str | None
    path: str | None
    size_bytes: int | None
    files: list[DatabaseFile]


class DatabaseYearRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
