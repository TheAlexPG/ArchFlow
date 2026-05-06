import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.agent_chat_message import MessageRole

# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

ContextKind = Literal["diagram", "object", "workspace", "none"]


class AgentChatContext(BaseModel):
    kind: ContextKind
    id: uuid.UUID | None = None
    draft_id: uuid.UUID | None = None
    parent_diagram_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class AgentChatMessageRead(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    sequence: int
    role: MessageRole
    content_text: str | None = None
    content_json: dict | None = None
    tool_call_id: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: Decimal | None = None
    is_compacted: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class AgentChatSessionRead(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: str
    actor_user_id: uuid.UUID | None = None
    actor_api_key_id: uuid.UUID | None = None
    context: AgentChatContext | None = None
    title: str | None = None
    compaction_stage: int
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime
    # Populated only on detail view (GET /sessions/{id})
    messages: list[AgentChatMessageRead] | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# List wrapper (paginated)
# ---------------------------------------------------------------------------


class AgentChatSessionList(BaseModel):
    items: list[AgentChatSessionRead]
    total: int
    limit: int
    offset: int
