import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DraftStatus(str, enum.Enum):
    OPEN = "open"
    MERGED = "merged"
    DISCARDED = "discarded"


class Draft(Base, UUIDMixin, TimestampMixin):
    """Named feature branch that can contain N forked diagrams at once.

    When the user clicks "Draft new feature" on a diagram, we create a
    Draft row plus a DraftDiagram row that points at the source and its
    fork clone. Multiple live diagrams can be added to the same draft;
    each gets its own DraftDiagram row.

    ``apply`` iterates all DraftDiagrams and merges each fork back onto
    its source. ``discard`` deletes all fork clones and marks the Draft
    discarded for the audit trail.
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
    # Version snapshot that was "current" in the workspace when this draft
    # was forked. On apply we compare current main to this version to find
    # changes that happened in parallel — those are potential conflicts.
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="SET NULL"),
        default=None,
    )

    diagrams: Mapped[list["DraftDiagram"]] = relationship(
        "DraftDiagram",
        back_populates="draft",
        cascade="all, delete-orphan",
    )


class DraftDiagram(Base, UUIDMixin, TimestampMixin):
    """Junction table: one row per (draft, source diagram) pair.

    A live diagram can appear in multiple open drafts simultaneously;
    each draft keeps its own isolated fork clone.
    """

    __tablename__ = "draft_diagrams"

    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="CASCADE")
    )
    source_diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagrams.id", ondelete="CASCADE")
    )
    forked_diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagrams.id", ondelete="CASCADE")
    )

    draft: Mapped["Draft"] = relationship("Draft", back_populates="diagrams")
    source_diagram = relationship(
        "Diagram", foreign_keys=[source_diagram_id], viewonly=True
    )
    forked_diagram = relationship(
        "Diagram", foreign_keys=[forked_diagram_id], viewonly=True
    )

    __table_args__ = (
        UniqueConstraint("draft_id", "source_diagram_id", name="uq_draft_source_diagram"),
    )
