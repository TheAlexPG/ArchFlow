import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ConnectionDirection(str, enum.Enum):
    UNIDIRECTIONAL = "unidirectional"
    BIDIRECTIONAL = "bidirectional"


class Connection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "connections"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="CASCADE")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(Text, default=None)
    protocol: Mapped[str | None] = mapped_column(String(100), default=None)
    direction: Mapped[ConnectionDirection] = mapped_column(
        Enum(ConnectionDirection, name="connection_direction"),
        default=ConnectionDirection.UNIDIRECTIONAL,
    )
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)

    # Relationships
    source = relationship("ModelObject", foreign_keys=[source_id], back_populates="source_connections")
    target = relationship("ModelObject", foreign_keys=[target_id], back_populates="target_connections")

    __table_args__ = (
        Index("ix_connections_source_id", "source_id"),
        Index("ix_connections_target_id", "target_id"),
        Index("ix_connections_source_target", "source_id", "target_id"),
    )
