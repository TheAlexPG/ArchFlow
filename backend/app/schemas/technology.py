import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.technology import TechCategory

_ICONIFY_NAME_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


def _validate_iconify(value: str) -> str:
    if not _ICONIFY_NAME_RE.match(value):
        raise ValueError(
            "iconify_name must match '<prefix>:<name>' (lowercase, digits, dashes)"
        )
    return value


def _validate_slug(value: str) -> str:
    if not _SLUG_RE.match(value):
        raise ValueError(
            "slug must be lowercase letters/digits/dashes (1-64 chars, no leading/trailing dash)"
        )
    return value


class TechnologyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    slug: str | None = Field(None, max_length=64)
    iconify_name: str = Field(..., min_length=3, max_length=120)
    category: TechCategory
    color: str | None = Field(None, max_length=9)
    aliases: list[str] | None = None

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_slug(v)

    @field_validator("iconify_name")
    @classmethod
    def _check_iconify(cls, v: str) -> str:
        return _validate_iconify(v)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _COLOR_RE.match(v):
            raise ValueError("color must be hex like #RRGGBB or #RRGGBBAA")
        return v


class TechnologyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    iconify_name: str | None = Field(None, min_length=3, max_length=120)
    category: TechCategory | None = None
    color: str | None = Field(None, max_length=9)
    aliases: list[str] | None = None

    @field_validator("iconify_name")
    @classmethod
    def _check_iconify(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_iconify(v)

    @field_validator("color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _COLOR_RE.match(v):
            raise ValueError("color must be hex like #RRGGBB or #RRGGBBAA")
        return v


class TechnologyResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    slug: str
    name: str
    iconify_name: str
    category: TechCategory
    color: str | None
    aliases: list[str] | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TechnologyDeleteConflict(BaseModel):
    """Body returned by DELETE /technologies/{id} when references exist."""

    object_refs: int
    connection_refs: int
    detail: str = "Technology is referenced by objects/connections"
