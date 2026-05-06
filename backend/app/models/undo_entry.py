import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class UndoTargetType(str, enum.Enum):
    OBJECT = "object"
    CONNECTION = "connection"
    DIAGRAM_OBJECT = "diagram_object"
    EDGE_PROPERTY = "edge_property"
    COMMENT = "comment"


class UndoAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class UndoState(str, enum.Enum):
    ACTIVE = "active"
    UNDONE = "undone"
    SKIPPED = "skipped"


class UndoEntry(Base, UUIDMixin):
    """One row per coalesced logical action by one user on one diagram.

    See docs/superpowers/specs/2026-05-04-per-user-undo-design.md for the
    full data model. The cursor is `MAX(seq) WHERE state='active'`,
    derived — no separate cursor table.
    """

    __tablename__ = "undo_entries"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diagrams.id", ondelete="CASCADE"),
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drafts.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )

    seq: Mapped[int] = mapped_column(BigInteger)

    target_type: Mapped[UndoTargetType] = mapped_column(
        Enum(
            UndoTargetType,
            name="undo_target_type",
            values_callable=lambda e: [v.value for v in e],
        )
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    action: Mapped[UndoAction] = mapped_column(
        Enum(
            UndoAction,
            name="undo_action",
            values_callable=lambda e: [v.value for v in e],
        )
    )

    forward_summary: Mapped[str] = mapped_column(Text)

    inverse_payload: Mapped[dict] = mapped_column(JSONB)
    redo_payload: Mapped[dict | None] = mapped_column(JSONB, default=None)
    after_state: Mapped[dict | None] = mapped_column(JSONB, default=None)

    coalesce_key: Mapped[str] = mapped_column(Text)

    state: Mapped[UndoState] = mapped_column(
        Enum(
            UndoState,
            name="undo_state",
            values_callable=lambda e: [v.value for v in e],
        ),
        default=UndoState.ACTIVE,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    __table_args__ = (
        Index(
            "ix_undo_entries_stack",
            "user_id", "diagram_id", "draft_id", seq.desc(),
        ),
        # The coalesce + sweep + target indexes are created in the migration
        # with options the declarative API doesn't express cleanly (partial
        # WHERE on coalesce, multi-column on sweep). They exist physically;
        # they just don't appear here.
    )
