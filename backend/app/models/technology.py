import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TechCategory(str, enum.Enum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    CLOUD = "cloud"
    SAAS = "saas"
    TOOL = "tool"
    PROTOCOL = "protocol"
    OTHER = "other"


class Technology(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "technologies"

    # NULL = built-in (globally visible across all workspaces). Non-null =
    # workspace-scoped custom entry.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        default=None,
    )
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    iconify_name: Mapped[str] = mapped_column(String(120))
    category: Mapped[TechCategory] = mapped_column(
        Enum(TechCategory, name="tech_category")
    )
    color: Mapped[str | None] = mapped_column(String(9), default=None)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(String), default=None)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    __table_args__ = (
        # Slug is unique within a workspace, and uniquely identifies a built-in
        # (workspace_id IS NULL). Two partial indexes because Postgres treats
        # NULLs as distinct by default in a regular unique constraint.
        Index(
            "uq_technologies_builtin_slug",
            "slug",
            unique=True,
            postgresql_where="workspace_id IS NULL",
        ),
        Index(
            "uq_technologies_workspace_slug",
            "workspace_id",
            "slug",
            unique=True,
            postgresql_where="workspace_id IS NOT NULL",
        ),
        Index("ix_technologies_workspace_id", "workspace_id"),
        Index("ix_technologies_category", "category"),
    )
