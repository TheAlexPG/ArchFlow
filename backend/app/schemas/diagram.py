import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.diagram import DiagramType


class DiagramCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: DiagramType
    description: str | None = None
    scope_object_id: uuid.UUID | None = None
    settings: dict | None = None


class DiagramUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    type: DiagramType | None = None
    description: str | None = None
    scope_object_id: uuid.UUID | None = None
    settings: dict | None = None


class DiagramResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: DiagramType
    description: str | None = None
    scope_object_id: uuid.UUID | None = None
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiagramObjectCreate(BaseModel):
    object_id: uuid.UUID
    position_x: float = 0.0
    position_y: float = 0.0
    width: float | None = None
    height: float | None = None


class DiagramObjectUpdate(BaseModel):
    position_x: float | None = None
    position_y: float | None = None
    width: float | None = None
    height: float | None = None


class DiagramObjectResponse(BaseModel):
    id: uuid.UUID
    diagram_id: uuid.UUID
    object_id: uuid.UUID
    position_x: float
    position_y: float
    width: float | None = None
    height: float | None = None

    model_config = {"from_attributes": True}
