import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Notification(Base, UUIDMixin, TimestampMixin):
    """Per-user notification row. Mentions, draft applied, etc.

    kind is an open string so new notification types can ship without
    schema migrations — the frontend renders based on it.
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text, default=None)
    target_url: Mapped[str | None] = mapped_column(String(512), default=None)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user = relationship("User")
