import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class AccessLevel(str, enum.Enum):
    """What a team is allowed to do on an individual diagram."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class Team(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "teams"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    members = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_team_slug_per_workspace"),
    )


class TeamMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "team_members"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    team = relationship("Team", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_user_per_team"),
    )


class DiagramAccess(Base, UUIDMixin, TimestampMixin):
    """Grants access to a specific diagram — either to a team or to a
    single user.

    Each row has exactly one grantee: team_id set and user_id null, OR
    user_id set and team_id null. The DB enforces this with a CHECK
    constraint and two partial unique indexes (see migration 648de0788239).

    When no DiagramAccess rows exist for a diagram, it falls back to
    workspace-wide visibility (every workspace member can see it, subject to
    their workspace role). As soon as ANY grant exists, the diagram becomes
    restricted and is only visible to the granted teams + granted users
    (plus workspace admins/owners).
    """

    __tablename__ = "diagram_access"

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diagrams.id", ondelete="CASCADE"),
        index=True,
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        index=True,
        default=None,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        default=None,
    )
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(
            AccessLevel,
            name="access_level",
            values_callable=lambda e: [v.value for v in e],
        ),
        default=AccessLevel.READ,
    )
