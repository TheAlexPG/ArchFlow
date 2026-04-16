import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.draft import DraftStatus


class DraftCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class DraftUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class DraftItemResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID | None = None
    baseline: dict[str, Any] | None = None
    proposed_state: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DraftItemCreate(BaseModel):
    target_type: str = "object"
    target_id: uuid.UUID | None = None  # None for brand-new creates
    proposed_state: dict[str, Any]


class DraftItemUpdate(BaseModel):
    proposed_state: dict[str, Any]


class DraftResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: DraftStatus
    author_id: uuid.UUID | None = None
    items: list[DraftItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
