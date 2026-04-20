import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class VersionSource(str, enum.Enum):
    """Why this version was created.

    apply       → persisted when a draft is applied onto main
    manual      → admin hit "Create snapshot now"
    scheduled   → cron job (versions-004, later)
    revert      → created when the user reverts to an older version (new
                  snapshot = state *after* revert, so revert itself is
                  auditable and also revertable)
    """

    APPLY = "apply"
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    REVERT = "revert"


class Version(Base, UUIDMixin, TimestampMixin):
    """Immutable snapshot of the full workspace model state.

    snapshot_data is a self-contained JSONB blob with every object,
    connection, and diagram in the workspace at the moment the snapshot was
    taken. Readers diff two versions without touching the live tables.
    """

    __tablename__ = "versions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    label: Mapped[str] = mapped_column(String(64))
    source: Mapped[VersionSource] = mapped_column(
        Enum(
            VersionSource,
            name="version_source",
            values_callable=lambda e: [v.value for v in e],
        )
    )
    # Set when source == apply so we can link back to the draft that
    # produced this snapshot. Other sources leave it null.
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drafts.id", ondelete="SET NULL"),
        default=None,
    )
    snapshot_data: Mapped[dict] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    created_by = relationship("User")
