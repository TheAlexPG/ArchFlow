import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DraftStatus(str, enum.Enum):
    OPEN = "open"
    MERGED = "merged"
    DISCARDED = "discarded"


class Draft(Base, UUIDMixin, TimestampMixin):
    """Named proposal of changes (IcePanel-style).

    A draft collects planned object edits (DraftItem rows) and can be
    compared side-by-side against the live state, then applied or
    discarded. Live model is untouched until Apply.
    """

    __tablename__ = "drafts"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, name="draft_status"), default=DraftStatus.OPEN
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )

    items = relationship(
        "DraftItem", back_populates="draft", cascade="all, delete-orphan"
    )


class DraftItem(Base, UUIDMixin, TimestampMixin):
    """One proposed edit inside a draft.

    For v1 we only track object edits (target_type=object). `proposed_state`
    holds the full ModelObject field dict as the user wants it. `baseline`
    captures the live object's state when the draft item was created so
    the diff is stable even if live changes before Apply.
    """

    __tablename__ = "draft_items"

    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="CASCADE")
    )
    # For v1 we only handle target_type='object'; leaving the column open
    # for connection/diagram edits in a follow-up.
    target_type: Mapped[str] = mapped_column(String(32), default="object")
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None
    )  # null for creates
    baseline: Mapped[dict | None] = mapped_column(JSONB, default=None)
    proposed_state: Mapped[dict] = mapped_column(JSONB)

    draft = relationship("Draft", back_populates="items")

    __table_args__ = (Index("ix_draft_items_draft_id", "draft_id"),)
