import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class ActivityTargetType(str, enum.Enum):
    OBJECT = "object"
    CONNECTION = "connection"
    DIAGRAM = "diagram"


class ActivityAction(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


class ActivityLog(Base, UUIDMixin):
    """
    Append-only log of changes to objects, connections, and diagrams.

    Powers:
    - per-object History tab (filter by target_type + target_id)
    - global activity feed (future)
    - audit trail for Phase 4 collaboration

    `changes` shape for action=updated:
        {"name": {"before": "Old", "after": "New"}, "status": {...}}
    For action=created/deleted: snapshot of the row as a single dict, or None.
    """

    __tablename__ = "activity_log"

    target_type: Mapped[ActivityTargetType] = mapped_column(
        Enum(ActivityTargetType, name="activity_target_type")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    action: Mapped[ActivityAction] = mapped_column(
        Enum(ActivityAction, name="activity_action")
    )
    changes: Mapped[dict | None] = mapped_column(JSONB, default=None)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_activity_log_target", "target_type", "target_id"),
        Index("ix_activity_log_created_at", "created_at"),
    )
