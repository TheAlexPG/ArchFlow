import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    created_at: datetime
    undo_settings: dict = {}

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """Self-update fields. Only fields that are explicitly provided are
    written. All-optional shape; PATCH semantics."""
    undo_settings: dict | None = None

    model_config = {"from_attributes": True}
