import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentAccessLevel(str, enum.Enum):
    """Per-user agent access policy for a workspace member.

    none       AI agent features are hidden for this member.
    read_only  Agent can read workspace data but cannot make edits (default).
    full       Agent can read and write on behalf of this member.
    """

    NONE = "none"
    READ_ONLY = "read_only"
    FULL = "full"


class Role(str, enum.Enum):
    """Permission tiers for a workspace member.

    owner   full control, manage workspace + members
    admin   manage content + invite members, can't delete workspace
    editor  create/edit/delete model entities
    reviewer read + comment, open drafts
    viewer  read-only
    """

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)

    workspaces = relationship("Workspace", back_populates="organization")


class Workspace(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workspaces"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120))

    organization = relationship("Organization", back_populates="workspaces")
    members = relationship(
        "WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_workspace_slug_per_org"),
    )


class WorkspaceMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="workspace_role",
            values_callable=lambda enum: [e.value for e in enum],
        )
    )

    agent_access: Mapped[AgentAccessLevel] = mapped_column(
        Enum(
            AgentAccessLevel,
            name="agent_access_level",
            values_callable=lambda e: [v.value for v in e],
        ),
        nullable=False,
        default=AgentAccessLevel.READ_ONLY,
        server_default="read_only",
    )
    agent_access_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    agent_access_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_member_per_workspace"),
    )
