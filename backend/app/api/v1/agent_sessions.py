"""A2A: list / get / stream-reconnect / cancel / respond / delete sessions.

Sibling router to ``/agents/*`` (see :mod:`app.api.v1.agents`).  We keep the
prefix ``/agents/sessions`` rather than nesting under ``/agents/{id}/...``
because sessions are agent-agnostic at the API level — a single actor can
list across all agents in one call.

Spec references:
- §5.1   endpoint table
- §5.4   reconnect via Last-Event-ID + 5-min Redis TTL → 410 Gone
- §5.5   sessions scoped to actor

Auth model (mirrors :mod:`app.api.v1.agents`):
- API-key bearer (``ak_…``): actor=ApiKey; sessions filtered by
  ``actor_api_key_id``.
- Session/JWT bearer: actor=User; sessions filtered by ``actor_user_id``.
- Cross-actor lookup → 404 (does not leak existence).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.redis import redis_client
from app.models.user import User
from app.services import agent_event_log_service, agent_session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/sessions", tags=["agents"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SessionListItem(BaseModel):
    id: UUID
    workspace_id: UUID
    agent_id: str
    title: str | None
    context_kind: str
    context_id: UUID | None
    context_draft_id: UUID | None
    last_message_at: str
    created_at: str


class SessionListResponse(BaseModel):
    items: list[SessionListItem]
    next_cursor: str | None


class MessageRead(BaseModel):
    id: UUID
    sequence: int
    role: str
    content_text: str | None = None
    content_json: dict | None = None
    tool_call_id: str | None = None
    created_at: str
    is_compacted: bool


class SessionDetailResponse(SessionListItem):
    messages: list[MessageRead] = Field(default_factory=list)


class CancelResponse(BaseModel):
    cancelled_at: str


class RespondBody(BaseModel):
    tool_call_id: str
    choice_id: str
    extra: dict | None = None


class RespondResponse(BaseModel):
    stored: bool
    tool_call_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actor_filter(request: Request, current_user: User) -> dict[str, UUID | None]:
    """Return ``{actor_user_id, actor_api_key_id}`` for the current request."""
    api_key = getattr(request.state, "api_key", None)
    if api_key is not None:
        return {
            "actor_user_id": None,
            "actor_api_key_id": api_key.id,
        }
    return {
        "actor_user_id": current_user.id,
        "actor_api_key_id": None,
    }


def _serialize_session(session: Any) -> SessionListItem:
    last = session.last_message_at
    created = session.created_at
    return SessionListItem(
        id=session.id,
        workspace_id=session.workspace_id,
        agent_id=session.agent_id,
        title=session.title,
        context_kind=session.context_kind,
        context_id=session.context_id,
        context_draft_id=session.context_draft_id,
        last_message_at=last.isoformat() if isinstance(last, datetime) else str(last or ""),
        created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
    )


def _serialize_message(msg: Any) -> MessageRead:
    role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
    created = msg.created_at
    return MessageRead(
        id=msg.id,
        sequence=msg.sequence,
        role=role,
        content_text=msg.content_text,
        content_json=msg.content_json,
        tool_call_id=msg.tool_call_id,
        created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
        is_compacted=bool(msg.is_compacted),
    )


def _format_sse(event_id: int | None, kind: str, payload: dict) -> str:
    """Render one SSE frame.

    Each event is at most three lines + a blank terminator: id (optional),
    event, data (single line of JSON).
    """
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {kind}")
    lines.append(f"data: {json.dumps(payload, default=str)}")
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=SessionListResponse)
async def list_sessions_endpoint(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_id: str | None = Query(None),
    context_kind: str | None = Query(None),
    workspace_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
) -> SessionListResponse:
    """List sessions for the current actor.

    Filtering is *additive*: you may narrow by ``agent_id``, ``context_kind``,
    or ``workspace_id``.  Pagination is cursor-based (opaque, base64
    encoding of ``{last, id}``).  See spec §5.5.
    """
    actor = _actor_filter(request, current_user)
    sessions, next_cursor = await agent_session_service.list_sessions(
        db,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
        workspace_id=workspace_id,
        agent_id=agent_id,
        context_kind=context_kind,
        limit=limit,
        cursor=cursor,
    )
    return SessionListResponse(
        items=[_serialize_session(s) for s in sessions],
        next_cursor=next_cursor,
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_endpoint(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionDetailResponse:
    """Return the session metadata + all (non-compacted) messages.

    404 if the session doesn't exist or belongs to a different actor.
    """
    actor = _actor_filter(request, current_user)
    session = await agent_session_service.get_session(
        db,
        session_id,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await agent_session_service.get_session_messages(db, session_id)
    base = _serialize_session(session)
    return SessionDetailResponse(
        **base.model_dump(),
        messages=[_serialize_message(m) for m in messages],
    )


@router.get("/{session_id}/stream")
async def reconnect_stream(
    session_id: UUID,
    request: Request,
    since: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Reconnect to a previously-running session.

    Replays events from ``agent_events:{session_id}`` whose sequence > ``since``.
    The Redis stream lives 5 minutes after the terminal ``done`` event
    (:func:`agent_event_log_service.finalize_stream`); past that, the key is
    gone and we surface ``410 Gone`` so the caller can post a fresh ``/chat``
    instead of polling forever.

    For *live* runs (no done marker yet), we replay what's there and then
    poll for new entries every 500 ms until we see the terminal ``done``
    event.  This is a simple polling loop — Phase 2 may switch to
    XREAD-blocking; for Phase 1, the polling cost is negligible vs the
    LLM cost of the run itself.

    The Last-Event-ID header overrides ``?since`` when both are supplied
    (matches the EventSource auto-reconnect semantics).
    """
    actor = _actor_filter(request, current_user)
    session = await agent_session_service.get_session(
        db,
        session_id,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Last-Event-ID takes precedence per EventSource spec.
    last_event_id_header = request.headers.get("Last-Event-ID")
    effective_since = since
    if last_event_id_header is not None:
        with contextlib.suppress(ValueError):
            effective_since = max(effective_since, int(last_event_id_header))

    # Probe the stream — if it has zero entries AND no `done` marker we
    # treat as expired (410). The "still running, no events yet" race is
    # rare in practice because the runtime emits ``session`` first thing.
    try:
        existing = await redis_client.xrange(
            agent_event_log_service.stream_key(session_id), count=1
        )
    except Exception:  # noqa: BLE001 — surface as expired
        existing = []

    if not existing:
        # Nothing to replay. If the stream key doesn't exist at all, we're
        # past the TTL or the session never ran — 410 either way.
        try:
            ttl = await redis_client.ttl(
                agent_event_log_service.stream_key(session_id)
            )
        except Exception:  # noqa: BLE001
            ttl = -2
        if ttl == -2:  # key doesn't exist
            raise HTTPException(
                status_code=410,
                detail="Session event stream expired; POST /chat to resume.",
            )

    async def _generate():
        seen_seq = effective_since
        # Replay everything past `seen_seq`.
        async for ev_id, kind, payload in agent_event_log_service.replay_since(
            redis_client, session_id, seen_seq
        ):
            seen_seq = max(seen_seq, ev_id)
            yield _format_sse(ev_id, kind, payload)
            if kind == "done":
                return

        # If we got here without a `done`, poll for new events. Bound the
        # total wait so a stuck runtime doesn't keep clients open forever.
        deadline_seconds = 30 * 60  # 30 min hard cap on a reconnect session
        start = asyncio.get_event_loop().time()
        while True:
            if asyncio.get_event_loop().time() - start > deadline_seconds:
                yield _format_sse(
                    None,
                    "error",
                    {"code": "stream_timeout", "message": "reconnect window exceeded"},
                )
                return

            await asyncio.sleep(0.5)
            saw_done = False
            async for ev_id, kind, payload in agent_event_log_service.replay_since(
                redis_client, session_id, seen_seq
            ):
                seen_seq = max(seen_seq, ev_id)
                yield _format_sse(ev_id, kind, payload)
                if kind == "done":
                    saw_done = True
            if saw_done:
                return

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post(
    "/{session_id}/cancel",
    response_model=CancelResponse,
    status_code=202,
)
async def cancel_endpoint(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelResponse:
    """Set the Redis cancel flag.  The runtime sees it between events and
    finalises gracefully with ``cancelled`` + ``done`` (forced_finalize="cancelled").
    """
    actor = _actor_filter(request, current_user)
    session = await agent_session_service.get_session(
        db,
        session_id,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    await agent_session_service.request_cancel(redis_client, session_id)
    return CancelResponse(cancelled_at=datetime.now(UTC).isoformat())


@router.post("/{session_id}/respond", response_model=RespondResponse)
async def respond_to_choice(
    session_id: UUID,
    body: RespondBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RespondResponse:
    """Record a user's reply to a ``requires_choice`` event.

    The runtime resumes by reading ``choice_response:{session_id}:{tool_call_id}``
    on the next dispatch — typically the frontend follows this call up with
    a fresh ``POST /chat`` whose runtime will pick up the stashed choice.
    """
    actor = _actor_filter(request, current_user)
    session = await agent_session_service.get_session(
        db,
        session_id,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    choice_payload = {"choice_id": body.choice_id, "extra": body.extra or {}}
    await agent_session_service.store_choice_response(
        redis_client, session_id, body.tool_call_id, choice_payload
    )
    return RespondResponse(stored=True, tool_call_id=body.tool_call_id)


@router.delete("/{session_id}", status_code=204)
async def delete_session_endpoint(
    session_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Hard delete the session + all messages.

    404 (not 403) if the session belongs to a different actor — same surface
    as a non-existent id, no existence leak.
    """
    actor = _actor_filter(request, current_user)
    deleted = await agent_session_service.delete_session(
        db,
        session_id,
        actor_user_id=actor["actor_user_id"],
        actor_api_key_id=actor["actor_api_key_id"],
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    # Best-effort cleanup of the redis stream + control flags.
    try:
        await redis_client.delete(
            agent_event_log_service.stream_key(session_id),
            f"cancel:{session_id}",
        )
    except Exception:  # noqa: BLE001
        logger.debug("redis cleanup on session delete failed", exc_info=True)
