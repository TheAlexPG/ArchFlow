from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


WEBHOOK_EVENTS = [
    "object.created",
    "object.updated",
    "object.deleted",
    "connection.created",
    "connection.updated",
    "connection.deleted",
    "diagram.created",
    "diagram.updated",
    "diagram.deleted",
    "draft.applied",
]


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(min_length=1)


class WebhookResponse(BaseModel):
    id: UUID
    url: str
    events: list[str]
    enabled: bool
    failure_count: int
    last_delivery_at: datetime | None
    last_status: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookWithSecret(WebhookResponse):
    secret: str
