import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Flow(Base, UUIDMixin, TimestampMixin):
    """
    A named sequence of connection hops telling a user/data journey through
    a diagram. Supports branching: each step optionally carries a `branch`
    tag so alternative paths (e.g. "happy path" vs "Google OAuth") can live
    inside the same flow.

    `steps` is JSONB for simplicity. Each entry:
        {
          "id": str,                # stable uuid within the flow
          "connection_id": uuid,    # edge to traverse
          "branch": str | null,     # null = main path
          "note": str | null
        }

    Playback on the frontend walks the list in order for the selected branch
    (or the main path). This keeps the v1 schema trivial while still letting
    flows diverge visually.
    """

    __tablename__ = "flows"

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diagrams.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    steps: Mapped[list] = mapped_column(JSONB, default=list)

    diagram = relationship("Diagram", foreign_keys=[diagram_id])

    __table_args__ = (Index("ix_flows_diagram_id", "diagram_id"),)
