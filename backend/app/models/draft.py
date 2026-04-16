import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DraftStatus(str, enum.Enum):
    OPEN = "open"
    MERGED = "merged"
    DISCARDED = "discarded"


class Draft(Base, UUIDMixin, TimestampMixin):
    """Named branch of a diagram.

    When the user clicks "Draft new feature" on a diagram, we create a
    Draft row, then fork the whole diagram (clone its Diagram row plus
    every ModelObject, Connection, and DiagramObject it references) and
    point ``forked_diagram_id`` at the clone. The user edits the clone on
    the normal canvas in isolation; draft-scoped rows carry ``draft_id``
    so default reads of the live model skip them.

    ``apply`` copies the forked state onto the live source objects (via
    their ``source_object_id`` / ``source_connection_id`` back-pointers)
    and deletes what's left of the fork. ``discard`` just deletes the
    fork and keeps the Draft row for the audit trail.
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

    # Which live diagram this draft was forked from.
    source_diagram_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diagrams.id", ondelete="SET NULL"),
        default=None,
    )
    # The cloned diagram the user edits inside this draft.
    forked_diagram_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diagrams.id", ondelete="SET NULL"),
        default=None,
    )

    source_diagram = relationship(
        "Diagram", foreign_keys=[source_diagram_id], viewonly=True
    )
    forked_diagram = relationship(
        "Diagram", foreign_keys=[forked_diagram_id], viewonly=True
    )
