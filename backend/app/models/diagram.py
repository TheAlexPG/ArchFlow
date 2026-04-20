import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DiagramType(str, enum.Enum):
    SYSTEM_LANDSCAPE = "system_landscape"
    SYSTEM_CONTEXT = "system_context"
    CONTAINER = "container"
    COMPONENT = "component"
    CUSTOM = "custom"


class Diagram(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "diagrams"

    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[DiagramType] = mapped_column(Enum(DiagramType, name="diagram_type"))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    scope_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="SET NULL"), default=None
    )
    settings: Mapped[dict | None] = mapped_column(JSONB, default=None)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when this diagram is the forked copy inside a draft. Live queries
    # hide it; the draft API surfaces it explicitly.
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drafts.id", ondelete="CASCADE"),
        default=None,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        default=None,
    )
    pack_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diagram_packs.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )

    # Relationships
    scope_object = relationship("ModelObject", foreign_keys=[scope_object_id])
    objects = relationship("DiagramObject", back_populates="diagram", cascade="all, delete-orphan")


class DiagramObject(Base, UUIDMixin):
    """Junction table: per-diagram position for each object (ADR-002)."""

    __tablename__ = "diagram_objects"

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagrams.id", ondelete="CASCADE")
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="CASCADE")
    )
    position_x: Mapped[float] = mapped_column(default=0.0)
    position_y: Mapped[float] = mapped_column(default=0.0)
    width: Mapped[float | None] = mapped_column(default=None)
    height: Mapped[float | None] = mapped_column(default=None)

    # Relationships
    diagram = relationship("Diagram", back_populates="objects")
    object = relationship("ModelObject", back_populates="diagram_placements")

    __table_args__ = (
        Index("ix_diagram_objects_diagram_id", "diagram_id"),
        Index("ix_diagram_objects_object_id", "object_id"),
        Index("uq_diagram_object", "diagram_id", "object_id", unique=True),
    )
