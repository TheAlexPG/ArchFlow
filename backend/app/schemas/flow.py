import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FlowStep(BaseModel):
    id: str
    connection_id: uuid.UUID
    branch: str | None = None
    note: str | None = None


class FlowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    steps: list[FlowStep] = Field(default_factory=list)


class FlowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    steps: list[FlowStep] | None = None


class FlowResponse(BaseModel):
    id: uuid.UUID
    diagram_id: uuid.UUID
    name: str
    description: str | None = None
    steps: list[FlowStep]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
