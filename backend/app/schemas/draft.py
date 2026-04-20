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


class DraftDiagramResponse(BaseModel):
    id: uuid.UUID
    draft_id: uuid.UUID
    source_diagram_id: uuid.UUID
    forked_diagram_id: uuid.UUID
    source_diagram_name: str | None = None
    forked_diagram_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DraftResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    status: DraftStatus
    author_id: uuid.UUID | None = None
    diagrams: list[DraftDiagramResponse] = []
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


class PerDiagramDiff(BaseModel):
    source_diagram_id: str
    forked_diagram_id: str
    source_diagram_name: str | None = None
    forked_diagram_name: str | None = None
    # Per-side status maps — key is the id of the row as it lives on that side.
    source_objects: dict[str, str]
    fork_objects: dict[str, str]
    source_connections: dict[str, str]
    fork_connections: dict[str, str]
    moved_on_fork: list[str]
    resized_on_fork: list[str]
    object_names: dict[str, str]
    summary: DraftDiffSummary


class DraftDiffResponse(BaseModel):
    total_summary: DraftDiffSummary
    per_diagram: list[PerDiagramDiff]
