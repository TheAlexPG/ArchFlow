import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.connection import ConnectionDirection, EdgeShape


class ConnectionCreate(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    label: str | None = None
    protocol: str | None = None
    direction: ConnectionDirection = ConnectionDirection.UNIDIRECTIONAL
    tags: list[str] | None = None
    source_handle: str | None = None
    target_handle: str | None = None
    shape: EdgeShape = EdgeShape.CURVED
    label_size: float = 11.0
    via_object_ids: list[str] | None = None


class ConnectionUpdate(BaseModel):
    label: str | None = None
    protocol: str | None = None
    direction: ConnectionDirection | None = None
    tags: list[str] | None = None
    source_handle: str | None = None
    target_handle: str | None = None
    shape: EdgeShape | None = None
    label_size: float | None = None
    via_object_ids: list[str] | None = None


class ConnectionResponse(BaseModel):
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    label: str | None = None
    protocol: str | None = None
    direction: ConnectionDirection
    tags: list[str] | None = None
    source_handle: str | None = None
    target_handle: str | None = None
    shape: EdgeShape
    label_size: float
    via_object_ids: list[str] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
