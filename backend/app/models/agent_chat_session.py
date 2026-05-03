import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.agent_chat_message import AgentChatMessage
from app.models.base import Base


class AgentChatSession(Base):
    """A conversation session between an actor and an agent.

    Exactly one of actor_user_id / actor_api_key_id must be NOT NULL —
    enforced by the CHECK constraint and modelled here as a business rule:
    in-app users have actor_user_id set; A2A callers have actor_api_key_id set.

    compaction_stage tracks which step of the CompactionLadder was last applied
    so that resuming a session continues from the right stage.
    """

    __tablename__ = "agent_chat_session"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
    )
    actor_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        default=None,
    )
    context_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    context_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None
    )
    context_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), default=None
    )
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    compaction_stage: Mapped[int] = mapped_column(SmallInteger, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=None, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=None, server_default="now()"
    )
    last_message_at: Mapped[datetime] = mapped_column(
        default=None, server_default="now()"
    )

    messages: Mapped[list[AgentChatMessage]] = relationship(
        "AgentChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="AgentChatMessage.sequence",
    )

    __table_args__ = (
        Index(
            "ix_agent_chat_session_ws_actor_last",
            "workspace_id",
            "actor_user_id",
            "last_message_at",
        ),
        CheckConstraint(
            "(actor_user_id IS NOT NULL)::int + (actor_api_key_id IS NOT NULL)::int = 1",
            name="ck_agent_chat_session_exactly_one_actor",
        ),
    )
