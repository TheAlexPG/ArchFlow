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


# ─── Diff ────────────────────────────────────────────────────
# Shape of the diff the frontend uses to paint change badges on
# the side-by-side compare canvases.

class DraftDiffSummary(BaseModel):
    added_objects: int
    modified_objects: int
    deleted_objects: int
    added_connections: int
    modified_connections: int
    deleted_connections: int
    moved_objects: int
    resized_objects: int


class DraftDiffResponse(BaseModel):
    summary: DraftDiffSummary
    # Per-side status maps — the key is the id of the row as it lives on
    # that side (live id on source, forked id on fork).
    source_objects: dict[str, str]  # id -> "unchanged" | "modified" | "deleted"
    fork_objects: dict[str, str]    # id -> "unchanged" | "modified" | "new"
    source_connections: dict[str, str]
    fork_connections: dict[str, str]
    # Which objects on the fork have been moved/resized vs. source. Keyed
    # by forked ModelObject id.
    moved_on_fork: list[str]
    resized_on_fork: list[str]
    # Names keyed by id — handy for the summary strip.
    object_names: dict[str, str]
