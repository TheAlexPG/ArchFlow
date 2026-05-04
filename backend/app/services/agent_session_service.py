"""Service layer for AgentChatSession CRUD + actor authorization checks.

Sister service to :mod:`app.services.agent_event_log_service` (Redis stream
for SSE replay).  This module owns the **DB-side** CRUD: list / get / delete
sessions, fetch messages, plus the Redis-backed control flags that the
runtime polls (``cancel:{session_id}``) and the choice-resume stash that
``POST /sessions/{id}/respond`` writes for the next ``POST /chat`` call to
pick up (``choice_response:{session_id}:{tool_call_id}``).

Authorization model:
- A session is owned by exactly **one** actor — either ``actor_user_id`` or
  ``actor_api_key_id``.  All read/delete helpers take an optional
  ``actor_user_id`` / ``actor_api_key_id`` filter; cross-actor access
  silently returns ``None`` / ``False`` so the API layer can surface 404
  without leaking existence.
- Workspace-admin "see-all" view is deferred to a separate
  ``/agents/admin/sessions`` endpoint (spec §5.5, optional Phase 1).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_chat_message import AgentChatMessage
from app.models.agent_chat_session import AgentChatSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

CANCEL_TTL_SECONDS = 60
"""Cancel flag lives 60s — long enough to cover the slowest tool call, short
enough that an abandoned flag doesn't poison a re-used session id."""

CHOICE_RESPONSE_TTL_SECONDS = 5 * 60
"""User choice-response stash lives 5 minutes — matches the SSE replay
window from the event-log service so the resume call has a stable budget."""


def _cancel_key(session_id: UUID) -> str:
    return f"cancel:{session_id}"


def _choice_response_key(session_id: UUID, tool_call_id: str) -> str:
    return f"choice_response:{session_id}:{tool_call_id}"


# ---------------------------------------------------------------------------
# Cursor helpers (opaque, just b64(JSON))
# ---------------------------------------------------------------------------


def _encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode())
        decoded = json.loads(raw.decode())
        if isinstance(decoded, dict):
            return decoded
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None
    return None


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


async def list_sessions(
    db: AsyncSession,
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
    workspace_id: UUID | None = None,
    agent_id: str | None = None,
    context_kind: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[AgentChatSession], str | None]:
    """Return ``(sessions, next_cursor)`` for the given actor.

    Exactly one of ``actor_user_id`` / ``actor_api_key_id`` must be set —
    sessions are scoped to the actor that created them.  If both are
    ``None`` we silently return an empty page (defensive).

    Order: ``last_message_at DESC, id DESC``.  The cursor is opaque
    base64(JSON) of ``{last: ISO datetime, id: UUID}`` of the last row on
    the previous page.
    """
    if actor_user_id is None and actor_api_key_id is None:
        return [], None

    stmt = select(AgentChatSession)

    if actor_user_id is not None:
        stmt = stmt.where(AgentChatSession.actor_user_id == actor_user_id)
    if actor_api_key_id is not None:
        stmt = stmt.where(AgentChatSession.actor_api_key_id == actor_api_key_id)
    if workspace_id is not None:
        stmt = stmt.where(AgentChatSession.workspace_id == workspace_id)
    if agent_id is not None:
        stmt = stmt.where(AgentChatSession.agent_id == agent_id)
    if context_kind is not None:
        stmt = stmt.where(AgentChatSession.context_kind == context_kind)

    cursor_payload = _decode_cursor(cursor)
    if cursor_payload is not None:
        last = cursor_payload.get("last")
        last_id = cursor_payload.get("id")
        if last is not None and last_id is not None:
            try:
                last_dt = datetime.fromisoformat(last)
                last_uuid = UUID(last_id)
            except (TypeError, ValueError):
                last_dt = None
                last_uuid = None
            if last_dt is not None and last_uuid is not None:
                stmt = stmt.where(
                    (AgentChatSession.last_message_at < last_dt)
                    | (
                        (AgentChatSession.last_message_at == last_dt)
                        & (AgentChatSession.id < last_uuid)
                    )
                )

    stmt = stmt.order_by(
        AgentChatSession.last_message_at.desc(),
        AgentChatSession.id.desc(),
    ).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_row = rows[-1]
        next_cursor = _encode_cursor(
            {
                "last": last_row.last_message_at.isoformat()
                if last_row.last_message_at is not None
                else None,
                "id": str(last_row.id),
            }
        )

    return rows, next_cursor


async def get_session(
    db: AsyncSession,
    session_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
) -> AgentChatSession | None:
    """Return the session if it exists *and* is owned by the supplied actor.

    Cross-actor access (e.g. a user trying to view an api-key session)
    returns ``None`` so the caller can surface 404 without leaking
    existence.
    """
    stmt = select(AgentChatSession).where(AgentChatSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        return None

    if actor_user_id is not None:
        if session.actor_user_id != actor_user_id:
            return None
    elif actor_api_key_id is not None:
        if session.actor_api_key_id != actor_api_key_id:
            return None
    else:
        # No actor filter at all → only allow if both sides are None
        # (which can never happen given the CHECK constraint).  Treat as 404.
        return None

    return session


async def get_session_messages(
    db: AsyncSession,
    session_id: UUID,
    *,
    limit: int = 200,
    include_compacted: bool = False,
) -> list[AgentChatMessage]:
    """Return messages for *session_id* ordered by ``sequence`` ascending.

    By default, ``is_compacted=True`` rows are filtered out (LLM context-only
    messages are noise for UI history rendering).  Set ``include_compacted``
    to true for audit/debug views.
    """
    stmt = (
        select(AgentChatMessage)
        .where(AgentChatMessage.session_id == session_id)
        .order_by(AgentChatMessage.sequence.asc())
        .limit(limit)
    )
    if not include_compacted:
        stmt = stmt.where(AgentChatMessage.is_compacted.is_(False))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_session_title(
    db: AsyncSession,
    session_id: UUID,
    title: str,
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
) -> AgentChatSession | None:
    """Set the session ``title``. Truncates to the column's 255-char limit.

    Returns the updated session, or ``None`` if the session doesn't belong
    to the actor (caller maps to 404).
    """
    session = await get_session(
        db,
        session_id,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
    )
    if session is None:
        return None
    session.title = (title or "").strip()[:255] or None
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(
    db: AsyncSession,
    session_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    actor_api_key_id: UUID | None = None,
) -> bool:
    """Delete *session_id* (cascading messages).  Returns True on success."""
    session = await get_session(
        db,
        session_id,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
    )
    if session is None:
        return False

    # Message rows cascade via FK ON DELETE CASCADE — but our test FakeSession
    # doesn't model FK cascades, so we fall back to an explicit delete. Run
    # the message delete first for robustness in environments without FK
    # cascade.
    try:
        await db.execute(
            delete(AgentChatMessage).where(AgentChatMessage.session_id == session_id)
        )
    except Exception:  # noqa: BLE001 — cascade still kicks in via FK
        logger.debug(
            "explicit message delete failed for session=%s; relying on FK cascade",
            session_id,
            exc_info=True,
        )

    try:
        await db.execute(
            delete(AgentChatSession).where(AgentChatSession.id == session_id)
        )
    except Exception:  # noqa: BLE001 — last-ditch: try ORM delete
        try:
            await db.delete(session)  # type: ignore[attr-defined]
        except Exception:
            logger.warning(
                "delete_session: both core delete and ORM delete failed for %s",
                session_id,
                exc_info=True,
            )
            return False

    try:
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.debug("flush after session delete failed", exc_info=True)
    return True


# ---------------------------------------------------------------------------
# Cancel flag (Redis)
# ---------------------------------------------------------------------------


async def request_cancel(redis: Any, session_id: UUID) -> None:
    """Set ``cancel:{session_id}`` with a 60s TTL.

    Idempotent: subsequent calls just refresh the TTL.  The runtime polls
    :func:`is_cancel_requested` between events to honour the flag.
    """
    await redis.set(_cancel_key(session_id), "1", ex=CANCEL_TTL_SECONDS)


async def is_cancel_requested(redis: Any, session_id: UUID) -> bool:
    """Return True if the cancel flag is set for *session_id*."""
    val = await redis.get(_cancel_key(session_id))
    return val is not None


async def clear_cancel(redis: Any, session_id: UUID) -> None:
    """Drop the cancel flag (e.g. after the runtime emits ``cancelled``)."""
    try:
        await redis.delete(_cancel_key(session_id))
    except Exception:  # noqa: BLE001
        logger.debug("clear_cancel failed for session=%s", session_id, exc_info=True)


# ---------------------------------------------------------------------------
# Choice-response stash (Redis)
# ---------------------------------------------------------------------------


async def store_choice_response(
    redis: Any,
    session_id: UUID,
    tool_call_id: str,
    choice: dict,
) -> None:
    """Stash a user's reply to a ``requires_choice`` event.

    Keyed by ``choice_response:{session_id}:{tool_call_id}`` with a 5-minute
    TTL.  The runtime reads this on the next dispatch (re-driven via a fresh
    POST /chat) and resumes the suspended tool call.
    """
    raw = json.dumps(choice, default=str)
    await redis.set(
        _choice_response_key(session_id, tool_call_id),
        raw,
        ex=CHOICE_RESPONSE_TTL_SECONDS,
    )


async def get_choice_response(
    redis: Any,
    session_id: UUID,
    tool_call_id: str,
) -> dict | None:
    """Return the stashed choice (and remove it) or ``None`` if absent.

    The pop-on-read semantic means the runtime can't accidentally consume
    the same choice twice.
    """
    key = _choice_response_key(session_id, tool_call_id)
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        await redis.delete(key)
    except Exception:  # noqa: BLE001
        logger.debug("choice_response cleanup delete failed", exc_info=True)
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded
