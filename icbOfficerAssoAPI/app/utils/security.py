"""Security utilities — JWT tokens, password hashing and role checks."""

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.admin_user import AdminUser, Role

security_scheme = HTTPBearer(auto_error=True)
optional_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def find_user(db: AsyncSession, username: str) -> AdminUser | None:
    """Usernames are not case sensitive: "ec1" signs in as EC1."""
    result = await db.execute(select(AdminUser).where(func.lower(AdminUser.username) == username.strip().lower()))
    return result.scalar_one_or_none()


async def _user_from_token(token: str, db: AsyncSession) -> AdminUser:
    payload = decode_access_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = await find_user(db, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    """Dependency: any signed-in user (401 otherwise)."""
    return await _user_from_token(credentials.credentials, db)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_scheme),
    db: AsyncSession = Depends(get_db),
) -> AdminUser | None:
    """Dependency: the user if a valid token was sent, otherwise None."""
    if credentials is None:
        return None
    try:
        return await _user_from_token(credentials.credentials, db)
    except HTTPException:
        return None


async def get_admin_user(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """Dependency: Super Admin or Admin (403 for an Election Commissioner)."""
    if user.role not in Role.ADMINS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the Super Admin and the Admin can do this")
    return user


async def get_superadmin(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """Dependency: the Super Admin only."""
    if user.role != Role.SUPERADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the Super Admin can do this")
    return user


async def get_ec_user(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    """Dependency: an Election Commissioner with a ballot number range."""
    if user.role != Role.EC or user.ballot_from is None or user.ballot_to is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an Election Commissioner can enter ballots")
    return user
