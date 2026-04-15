import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ObjectType(str, enum.Enum):
    SYSTEM = "system"
    ACTOR = "actor"
    EXTERNAL_SYSTEM = "external_system"
    GROUP = "group"
    APP = "app"
    STORE = "store"
    COMPONENT = "component"


class ObjectScope(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class ObjectStatus(str, enum.Enum):
    LIVE = "live"
    FUTURE = "future"
    DEPRECATED = "deprecated"
    REMOVED = "removed"


# Derived C4 level from object type
C4_LEVEL_MAP = {
    ObjectType.SYSTEM: "L1",
    ObjectType.ACTOR: "L1",
    ObjectType.EXTERNAL_SYSTEM: "L1",
    ObjectType.GROUP: "L2",
    ObjectType.APP: "L2",
    ObjectType.STORE: "L2",
    ObjectType.COMPONENT: "L3",
}


class ModelObject(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "model_objects"

    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[ObjectType] = mapped_column(Enum(ObjectType, name="object_type"))
    scope: Mapped[ObjectScope] = mapped_column(
        Enum(ObjectScope, name="object_scope"), default=ObjectScope.INTERNAL
    )
    status: Mapped[ObjectStatus] = mapped_column(
        Enum(ObjectStatus, name="object_status"), default=ObjectStatus.LIVE
    )
    description: Mapped[str | None] = mapped_column(Text, default=None)
    icon: Mapped[str | None] = mapped_column(String(100), default=None)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_objects.id", ondelete="SET NULL"), default=None
    )
    technology: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    owner_team: Mapped[str | None] = mapped_column(String(255), default=None)
    external_links: Mapped[dict | None] = mapped_column(JSONB, default=None)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=None)

    # Relationships
    parent = relationship("ModelObject", remote_side="ModelObject.id", back_populates="children")
    children = relationship("ModelObject", back_populates="parent", cascade="all, delete-orphan")
    source_connections = relationship(
        "Connection",
        foreign_keys="Connection.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    target_connections = relationship(
        "Connection",
        foreign_keys="Connection.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )
    diagram_placements = relationship(
        "DiagramObject", back_populates="object", cascade="all, delete-orphan"
    )

    @property
    def c4_level(self) -> str:
        return C4_LEVEL_MAP.get(self.type, "L1")

    __table_args__ = (
        Index("ix_model_objects_type", "type"),
        Index("ix_model_objects_parent_id", "parent_id"),
        Index("ix_model_objects_status", "status"),
        Index("ix_model_objects_owner_team", "owner_team"),
    )
