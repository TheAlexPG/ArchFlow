import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkspaceAgentSetting(Base):
    """Per-workspace agent configuration with optional server-side encryption.

    A row with ``agent_id=None`` represents a global workspace default for that
    key. A row with a non-NULL ``agent_id`` overrides the global default for
    that specific agent.

    Resolution order (highest → lowest priority):
    1. (workspace_id, agent_id, key)  — agent-specific override
    2. (workspace_id, NULL, key)       — global workspace default
    3. hardcoded application default
    """

    __tablename__ = "workspace_agent_setting"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL means this row is a global default for the entire workspace.
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Non-secret settings stored as plain JSONB.
    value_plain: Mapped[dict | None] = mapped_column(JSONB(astext_type=Text()), nullable=True)
    # Secret settings stored as Fernet-encrypted bytes.
    value_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Composite index for the resolution query pattern:
        # SELECT ... WHERE workspace_id=? AND agent_id IN (?, NULL)
        Index(
            "ix_workspace_agent_setting_workspace_agent",
            "workspace_id",
            "agent_id",
        ),
        # UNIQUE(workspace_id, agent_id, key) with NULL-safe semantics via two
        # partial indexes (Postgres treats NULLs as distinct in plain UNIQUEs).
        Index(
            "uq_workspace_agent_setting_with_agent",
            "workspace_id",
            "agent_id",
            "key",
            unique=True,
            postgresql_where="agent_id IS NOT NULL",
        ),
        Index(
            "uq_workspace_agent_setting_global",
            "workspace_id",
            "key",
            unique=True,
            postgresql_where="agent_id IS NULL",
        ),
    )
