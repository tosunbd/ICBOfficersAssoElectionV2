"""Pydantic schemas for authentication and user accounts."""

from pydantic import BaseModel, ConfigDict, Field

MIN_PASSWORD_LENGTH = 3  # the first passwords are short (EC1, admin ...); longer ones are encouraged in the UI


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    full_name: str | None = None
    role: str                       # superadmin | admin | ec
    ballot_from: int | None = None  # Election Commissioners: the ballot numbers they enter
    ballot_to: int | None = None


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str | None
    role: str
    ballot_from: int | None = None
    ballot_to: int | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)
