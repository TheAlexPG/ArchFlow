import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class CommentTargetType(str, enum.Enum):
    OBJECT = "object"
    CONNECTION = "connection"
    DIAGRAM = "diagram"


class CommentType(str, enum.Enum):
    """Matches IcePanel's typed comments plus a plain note."""

    QUESTION = "question"
    INACCURACY = "inaccuracy"
    IDEA = "idea"
    NOTE = "note"


class Comment(Base, UUIDMixin, TimestampMixin):
    """A typed comment on an object, connection, or diagram."""

    __tablename__ = "comments"

    target_type: Mapped[CommentTargetType] = mapped_column(
        Enum(CommentTargetType, name="comment_target_type")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    comment_type: Mapped[CommentType] = mapped_column(
        Enum(CommentType, name="comment_type"),
        default=CommentType.NOTE,
    )
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    # Canvas pin coordinates — set when the comment is placed as a floating
    # pin on the diagram (target_type=diagram). Null for per-object comments
    # that render inside the object sidebar.
    position_x: Mapped[float | None] = mapped_column(default=None)
    position_y: Mapped[float | None] = mapped_column(default=None)

    author = relationship("User", foreign_keys=[author_id])

    __table_args__ = (
        Index("ix_comments_target", "target_type", "target_id"),
        Index("ix_comments_created_at", "created_at"),
    )
