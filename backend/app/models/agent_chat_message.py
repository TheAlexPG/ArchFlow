import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM_SUMMARY = "system_summary"


class AgentChatMessage(Base):
    """A single message in an agent chat session.

    is_compacted=True means the message is kept for UI history but excluded
    from the LLM context window (it has been compacted away).
    """

    __tablename__ = "agent_chat_message"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_chat_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"),
        nullable=False,
    )
    content_text: Mapped[str | None] = mapped_column(Text, default=None)
    content_json: Mapped[dict | None] = mapped_column(JSONB, default=None)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), default=None)
    tokens_in: Mapped[int | None] = mapped_column(Integer, default=None)
    tokens_out: Mapped[int | None] = mapped_column(Integer, default=None)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), default=None)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(128), default=None)
    is_compacted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=None, server_default="now()"
    )

    session: Mapped["AgentChatSession"] = relationship(  # noqa: F821
        "AgentChatSession", back_populates="messages"
    )

    __table_args__ = (
        UniqueConstraint("session_id", "sequence", name="uq_agent_chat_message_session_seq"),
        Index("ix_agent_chat_message_session_seq", "session_id", "sequence"),
    )
