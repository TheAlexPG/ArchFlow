"""Pydantic schemas for undo endpoints."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UndoEntryRead(BaseModel):
    id: uuid.UUID
    seq: int
    state: str
    target_type: str
    target_id: uuid.UUID
    action: str
    forward_summary: str
    created_at: datetime
    updated_at: datetime
    undone_at: datetime | None = None

    model_config = {"from_attributes": True}


class UndoActionRequest(BaseModel):
    """POST /diagrams/{id}/undo body."""
    expected_seq: int | None = Field(
        default=None,
        description="Optimistic-concurrency guard. Server returns 409 if "
                    "the actual top-of-stack seq differs.",
    )


class UndoActionResponse(BaseModel):
    undone_entry: UndoEntryRead | None = None
    redone_entry: UndoEntryRead | None = None
    cursor_seq: int | None
    remaining_undo_count: int
    redo_count: int


class UndoHistoryResponse(BaseModel):
    entries: list[UndoEntryRead]
    cursor_seq: int | None


class UndoToRequest(BaseModel):
    expected_path_length: int | None = None


class UndoToResponse(BaseModel):
    applied: list[dict]   # [{ entry_id: UUID, direction: "undo"|"redo" }]
    cursor_seq: int | None
