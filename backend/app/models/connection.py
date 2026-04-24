import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ConnectionDirection(str, enum.Enum):
    UNIDIRECTIONAL = "unidirectional"
    BIDIRECTIONAL = "bidirectional"
    UNDIRECTED = "undirected"


class EdgeShape(str, enum.Enum):
    CURVED = "curved"
    STRAIGHT = "straight"
    STEP = "step"
    SMOOTHSTEP = "smoothstep"


class Connection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "connections"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="CASCADE")
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(Text, default=None)
    protocol_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=None
    )
    direction: Mapped[ConnectionDirection] = mapped_column(
        Enum(ConnectionDirection, name="connection_direction"),
        default=ConnectionDirection.UNIDIRECTIONAL,
    )
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    source_handle: Mapped[str | None] = mapped_column(String(50), default=None)
    target_handle: Mapped[str | None] = mapped_column(String(50), default=None)
    shape: Mapped[EdgeShape] = mapped_column(
        Enum(EdgeShape, name="edge_shape"), default=EdgeShape.SMOOTHSTEP
    )
    label_size: Mapped[float] = mapped_column(Float, default=11.0)
    via_object_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)

    # See ModelObject.draft_id for semantics — same scoping applies here.
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drafts.id", ondelete="CASCADE"),
        default=None,
    )
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connections.id", ondelete="SET NULL"),
        default=None,
    )

    # Relationships
    source = relationship(
        "ModelObject", foreign_keys=[source_id], back_populates="source_connections"
    )
    target = relationship(
        "ModelObject", foreign_keys=[target_id], back_populates="target_connections"
    )

    __table_args__ = (
        Index("ix_connections_source_id", "source_id"),
        Index("ix_connections_target_id", "target_id"),
        Index("ix_connections_source_target", "source_id", "target_id"),
    )
