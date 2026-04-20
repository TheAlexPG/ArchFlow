import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Webhook(Base, UUIDMixin, TimestampMixin):
    """Outbound HTTP subscription to model-change events.

    Delivery attaches an HMAC-SHA256 signature of the body keyed by `secret`
    (header: X-ArchFlow-Signature). On repeated failure the hook auto-disables.
    """

    __tablename__ = "webhooks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    secret: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_status: Mapped[int | None] = mapped_column(Integer, default=None)

    user = relationship("User")
