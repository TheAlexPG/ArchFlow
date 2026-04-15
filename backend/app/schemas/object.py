import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.object import ObjectScope, ObjectStatus, ObjectType


class ObjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: ObjectType
    scope: ObjectScope = ObjectScope.INTERNAL
    status: ObjectStatus = ObjectStatus.LIVE
    description: str | None = None
    icon: str | None = None
    parent_id: uuid.UUID | None = None
    technology: list[str] | None = None
    tags: list[str] | None = None
    owner_team: str | None = None
    external_links: dict | None = None
    metadata_: dict | None = Field(None, alias="metadata")

    model_config = {"populate_by_name": True}


class ObjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    type: ObjectType | None = None
    scope: ObjectScope | None = None
    status: ObjectStatus | None = None
    description: str | None = None
    icon: str | None = None
    parent_id: uuid.UUID | None = None
    technology: list[str] | None = None
    tags: list[str] | None = None
    owner_team: str | None = None
    external_links: dict | None = None
    metadata_: dict | None = Field(None, alias="metadata")

    model_config = {"populate_by_name": True}


class ObjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: ObjectType
    scope: ObjectScope
    status: ObjectStatus
    c4_level: str
    description: str | None = None
    icon: str | None = None
    parent_id: uuid.UUID | None = None
    technology: list[str] | None = None
    tags: list[str] | None = None
    owner_team: str | None = None
    external_links: dict | None = None
    metadata: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, obj) -> "ObjectResponse":
        return cls(
            id=obj.id,
            name=obj.name,
            type=obj.type,
            scope=obj.scope,
            status=obj.status,
            c4_level=obj.c4_level,
            description=obj.description,
            icon=obj.icon,
            parent_id=obj.parent_id,
            technology=obj.technology,
            tags=obj.tags,
            owner_team=obj.owner_team,
            external_links=obj.external_links,
            metadata=obj.metadata_,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
