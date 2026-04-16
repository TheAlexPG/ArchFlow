import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.draft import DraftStatus


class DraftCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class DraftUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class DraftFromDiagram(BaseModel):
    """Payload for starting a draft from an existing diagram."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class DraftResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: DraftStatus
    author_id: uuid.UUID | None = None
    source_diagram_id: uuid.UUID | None = None
    forked_diagram_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
