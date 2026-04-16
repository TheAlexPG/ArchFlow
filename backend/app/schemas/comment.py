import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.comment import CommentTargetType, CommentType


class CommentCreate(BaseModel):
    target_type: CommentTargetType
    target_id: uuid.UUID
    comment_type: CommentType = CommentType.NOTE
    body: str = Field(..., min_length=1, max_length=8000)
    position_x: float | None = None
    position_y: float | None = None


class CommentUpdate(BaseModel):
    comment_type: CommentType | None = None
    body: str | None = Field(None, min_length=1, max_length=8000)
    resolved: bool | None = None
    position_x: float | None = None
    position_y: float | None = None


class CommentAuthor(BaseModel):
    id: uuid.UUID
    email: str

    model_config = {"from_attributes": True}


class CommentResponse(BaseModel):
    id: uuid.UUID
    target_type: CommentTargetType
    target_id: uuid.UUID
    comment_type: CommentType
    body: str
    author_id: uuid.UUID | None = None
    author: CommentAuthor | None = None
    resolved: bool
    position_x: float | None = None
    position_y: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
