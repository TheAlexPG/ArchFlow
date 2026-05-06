"""A2A discovery + invoke + chat.

GET  /api/v1/agents          — list (task 034)
GET  /api/v1/agents/{id}     — descriptor (task 034)
POST /api/v1/agents/{id}/invoke — one-shot, JSON, idempotent (task 035)
POST /api/v1/agents/{id}/chat   — streaming SSE (task 036)

Spec §5.3 + §5.8 + §5.9 + §5.10.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import registry
from app.agents.errors import AgentError, BudgetExhausted, ContextOverflow, TurnLimitReached
from app.agents.runtime import ActorRef, ChatContext, InvokeRequest, InvokeResult, invoke
from app.agents.runtime import stream as runtime_stream
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.redis import redis_client
from app.models.api_key import ApiKey
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import agent_event_log_service
from app.services.rate_limit_service import (
    RateLimitExceeded,
    check_and_consume,
    default_limits_from_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

# ---------------------------------------------------------------------------
# Idempotency TTL
# ---------------------------------------------------------------------------

_IDEMPOTENCY_TTL_SECONDS = 86400  # 24 hours


# ---------------------------------------------------------------------------
# Discovery response models (task 034)
# ---------------------------------------------------------------------------


class AgentLimitsRead(BaseModel):
    turn_limit: int
    budget_usd: str  # Decimal serialised as str for JSON
    budget_scope: str


class AgentDescriptorRead(BaseModel):
    id: str
    name: str
    description: str
    schema_version: str
    surfaces: list[str]
    allowed_contexts: list[str]
    supported_modes: list[str]
    required_scope: str
    tools_overview: list[str]
    limits: AgentLimitsRead
    streaming: bool


class AgentsListResponse(BaseModel):
    agents: list[AgentDescriptorRead]


# ---------------------------------------------------------------------------
# Invoke request / response schemas (task 035)
# ---------------------------------------------------------------------------


class ChatContextBody(BaseModel):
    kind: Literal["workspace", "diagram", "object", "none"] = "none"
    id: UUID | None = None
    draft_id: UUID | None = None
    parent_diagram_id: UUID | None = None


class InvokeBody(BaseModel):
    session_id: UUID | None = None
    context: ChatContextBody = ChatContextBody()
    message: str
    mode: Literal["full", "read_only"] = "full"
    metadata: dict | None = None


class InvokeResponse(BaseModel):
    session_id: UUID
    agent_id: str
    final_message: str
    applied_changes: list[dict]
    tool_calls: int
    tokens: dict  # {in, out}
    cost_usd: str  # Decimal as str
    duration_ms: int
    forced_finalize: str | None
    warnings: list[str]


# ---------------------------------------------------------------------------
# Shared serialiser helper (discovery)
# ---------------------------------------------------------------------------


def _serialize_descriptor(d: registry.AgentDescriptor) -> AgentDescriptorRead:
    """Convert registry AgentDescriptor → response model."""
    return AgentDescriptorRead(
        id=d.id,
        name=d.name,
        description=d.description,
        schema_version=d.schema_version,
        surfaces=sorted(d.surfaces),
        allowed_contexts=sorted(d.allowed_contexts),
        supported_modes=list(d.supported_modes),
        required_scope=d.required_scope,
        tools_overview=list(d.tools_overview),
        limits=AgentLimitsRead(
            turn_limit=d.default_turn_limit,
            budget_usd=str(d.default_budget_usd),
            budget_scope=d.default_budget_scope,
        ),
        streaming=d.streaming,
    )


# ---------------------------------------------------------------------------
# Auth helpers (discovery)
# ---------------------------------------------------------------------------


def _get_api_key_scopes(request: Request) -> set[str] | None:
    """Return the API key's permissions as a set if the request used an API key.

    Returns None when the actor is a session-based User (JWT path), meaning
    no scope filter should be applied — workspace agent_access is used instead.
    """
    api_key = getattr(request.state, "api_key", None)
    if api_key is not None:
        return set(api_key.permissions or [])
    return None


# ---------------------------------------------------------------------------
# Error envelope helper (invoke)
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int,
    code: str,
    message: str,
    agent_id: str,
    details: dict | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "agent_id": agent_id,
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers or {})


# ---------------------------------------------------------------------------
# Actor resolution dependency (invoke)
# ---------------------------------------------------------------------------


async def get_current_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActorRef:
    """Resolve the caller as an ActorRef.

    If the request was authenticated via an ApiKey (stored on request.state by
    deps.get_current_user), return an api_key actor using the key's scopes.
    Otherwise return a user actor, resolving agent_access from the workspace
    membership.
    """
    api_key: ApiKey | None = getattr(request.state, "api_key", None)

    # Resolve workspace_id from X-Workspace-ID header (best-effort).
    workspace_id: UUID | None = None
    header_value = request.headers.get("X-Workspace-ID")
    if header_value:
        try:
            workspace_id = UUID(header_value)
        except ValueError:
            workspace_id = None

    if workspace_id is None:
        # Fall back to user's default workspace.
        from app.services import workspace_service

        ws = await workspace_service.get_default_workspace_for_user(db, current_user.id)
        workspace_id = ws.id if ws else uuid4()

    if api_key is not None:
        # Map ApiKey.permissions (["read", "write", "admin"]) → agents scopes.
        perms = set(api_key.permissions or [])
        scopes: list[str]
        if "admin" in perms:
            scopes = ["agents:admin"]
        elif "write" in perms:
            scopes = ["agents:write"]
        elif "read" in perms:
            scopes = ["agents:read"]
        else:
            scopes = ["agents:read"]
        return ActorRef(
            kind="api_key",
            id=api_key.id,
            workspace_id=workspace_id,
            scopes=tuple(scopes),
        )

    # User actor — fetch membership to get agent_access.
    agent_access: str = "read_only"
    try:
        result = await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == current_user.id,
                WorkspaceMember.workspace_id == workspace_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is not None:
            agent_access = member.agent_access.value  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        logger.debug("Failed to fetch workspace membership for agent_access", exc_info=True)

    return ActorRef(
        kind="user",
        id=current_user.id,
        workspace_id=workspace_id,
        agent_access=agent_access,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Idempotency helpers
# ---------------------------------------------------------------------------


def _body_hash(body: InvokeBody) -> str:
    serialized = json.dumps(body.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _idempotency_redis_key(actor: ActorRef, key: str) -> str:
    return f"idempotency:{actor.id}:{key}"


async def _get_cached_response(actor: ActorRef, key: str) -> dict | None:
    """Return the cached payload dict if the key exists, else None."""
    try:
        raw = await redis_client.get(_idempotency_redis_key(actor, key))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to read idempotency cache", exc_info=True)
        return None


async def _set_cached_response(actor: ActorRef, key: str, payload: dict) -> None:
    try:
        await redis_client.set(
            _idempotency_redis_key(actor, key),
            json.dumps(payload),
            ex=_IDEMPOTENCY_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to write idempotency cache", exc_info=True)


# ---------------------------------------------------------------------------
# Discovery endpoints (task 034)
# ---------------------------------------------------------------------------


@router.get("", response_model=AgentsListResponse)
async def list_agents(
    request: Request,
    surface: Literal["chat_bubble", "inline_button", "a2a"] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentsListResponse:
    """Return all agents visible to this actor.

    Filtering rules:
    - ApiKey bearer: filtered by key's ``permissions`` scopes. Workspace
      ``agent_access`` is NOT applied (as per spec §2.10).
    - Session (JWT) bearer: filtered by the user's ``agent_access`` on their
      active workspace. No scope filter.
    - Optional ``?surface=`` query narrows by surface in both cases.
    """
    actor_scopes = _get_api_key_scopes(request)

    workspace_agent_access: Literal["none", "read_only", "full"] | None = None
    if actor_scopes is None:
        # User actor — look up their agent_access in their workspace.
        result = await db.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == current_user.id)
            .order_by(WorkspaceMember.created_at)
            .limit(1)
        )
        membership = result.scalar_one_or_none()
        workspace_agent_access = (  # type: ignore[assignment]
            membership.agent_access.value if membership is not None else "none"
        )

    descriptors = registry.list_for_workspace(
        actor_scopes=actor_scopes,
        workspace_agent_access=workspace_agent_access,
        surface_filter=surface,
    )

    return AgentsListResponse(agents=[_serialize_descriptor(d) for d in descriptors])


@router.get("/{agent_id}", response_model=AgentDescriptorRead)
async def get_agent(
    agent_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentDescriptorRead:
    """Return a single agent descriptor.

    Returns 404 if the agent is unknown **or** if it would be filtered out
    for this actor (scope / workspace policy mismatch).
    """
    try:
        descriptor = registry.get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found") from exc

    actor_scopes = _get_api_key_scopes(request)

    workspace_agent_access: Literal["none", "read_only", "full"] | None = None
    if actor_scopes is None:
        result = await db.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == current_user.id)
            .order_by(WorkspaceMember.created_at)
            .limit(1)
        )
        membership = result.scalar_one_or_none()
        workspace_agent_access = membership.agent_access.value if membership is not None else "none"  # type: ignore[assignment]

    # Re-use list_for_workspace filter logic to check visibility.
    visible = registry.list_for_workspace(
        actor_scopes=actor_scopes,
        workspace_agent_access=workspace_agent_access,
    )
    visible_ids = {d.id for d in visible}
    if agent_id not in visible_ids:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return _serialize_descriptor(descriptor)


# ---------------------------------------------------------------------------
# POST /{agent_id}/invoke  (task 035)
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    agent_id: str,
    body: InvokeBody,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: ActorRef = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> InvokeResponse | JSONResponse:
    """One-shot invocation. Blocks until agent finishes. Use /chat for streaming."""

    # ── 1. Idempotency check ─────────────────────────────────────────────────
    current_body_hash = _body_hash(body) if idempotency_key else None

    if idempotency_key is not None:
        cached = await _get_cached_response(actor, idempotency_key)
        if cached is not None:
            cached_hash = cached.get("_body_hash")
            if cached_hash != current_body_hash:
                return _error_response(
                    status_code=status.HTTP_409_CONFLICT,
                    code="idempotency_conflict",
                    message="Idempotency-Key reused with a different request body.",
                    agent_id=agent_id,
                )
            # Same body — return the cached response (no re-run).
            return InvokeResponse(**cached["response"])

    # ── 2. Build InvokeRequest ───────────────────────────────────────────────
    chat_ctx = ChatContext(
        kind=body.context.kind,
        id=body.context.id,
        draft_id=body.context.draft_id,
        parent_diagram_id=body.context.parent_diagram_id,
    )
    req = InvokeRequest(
        agent_id=agent_id,
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=chat_ctx,
        message=body.message,
        mode=body.mode,
        session_id=body.session_id,
        metadata=body.metadata,
    )

    # ── 3. Invoke runtime + translate exceptions → HTTP ──────────────────────
    result: InvokeResult
    try:
        result = await invoke(req, db=db)
    except RateLimitExceeded as exc:
        return _error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            message=str(exc),
            agent_id=agent_id,
            details={"scope": str(exc.scope), "limit": exc.limit},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except BudgetExhausted as exc:
        return _error_response(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            code="agent_budget_exhausted",
            message=str(exc),
            agent_id=agent_id,
        )
    except TurnLimitReached as exc:
        return _error_response(
            status_code=status.HTTP_409_CONFLICT,
            code="turn_limit_reached",
            message=str(exc),
            agent_id=agent_id,
        )
    except ContextOverflow as exc:
        return _error_response(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            code="context_overflow",
            message=str(exc),
            agent_id=agent_id,
        )
    except PermissionError as exc:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
            message=str(exc),
            agent_id=agent_id,
        )
    except AgentError as exc:
        msg = str(exc)
        # agent_not_found is raised as AgentError with the registry's KeyError message.
        if "not found" in msg.lower() or "agent_not_found" in msg.lower():
            return _error_response(
                status_code=status.HTTP_404_NOT_FOUND,
                code="agent_not_found",
                message=msg,
                agent_id=agent_id,
            )
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message=msg,
            agent_id=agent_id,
        )

    # ── 4. Build response ────────────────────────────────────────────────────
    cost_str = str(result.cost_usd) if result.cost_usd is not None else "0"
    # tool_calls: uses applied_changes count as proxy; task 036 will wire the
    # real per-tool-call counter from graph instrumentation.
    tool_calls = len(result.applied_changes)

    response_payload = InvokeResponse(
        session_id=result.session_id,
        agent_id=result.agent_id,
        final_message=result.final_message,
        applied_changes=result.applied_changes,
        tool_calls=tool_calls,
        tokens={"in": result.tokens_in, "out": result.tokens_out},
        cost_usd=cost_str,
        duration_ms=result.duration_ms,
        forced_finalize=result.forced_finalize,
        warnings=result.warnings,
    )

    # ── 5. Store under Idempotency-Key (TTL 24 h) ───────────────────────────
    if idempotency_key is not None and current_body_hash is not None:
        await _set_cached_response(
            actor,
            idempotency_key,
            {
                "_body_hash": current_body_hash,
                "response": response_payload.model_dump(mode="json"),
            },
        )

    return response_payload


# ---------------------------------------------------------------------------
# POST /{agent_id}/chat  (task 036) — SSE streaming
# ---------------------------------------------------------------------------


# Heartbeat: idle gap before we emit `event: ping` (per spec §3.7 / §5.4).
_HEARTBEAT_INTERVAL_SECONDS = 25.0


def _format_sse(kind: str, event_id: int, payload: dict) -> str:
    """Encode one SSE message per the spec's wire format (§5.4)."""
    return (
        f"event: {kind}\n"
        f"id: {event_id}\n"
        f"data: {json.dumps(payload, default=str)}\n\n"
    )


async def _rate_limit_preflight(
    actor: ActorRef,
    db: AsyncSession,  # noqa: ARG001 — kept for call-site compatibility
    agent_id: str,  # noqa: ARG001 — kept for call-site compatibility
) -> None:
    """Run the same rate-limit pre-flight as ``runtime.stream`` but at the API
    layer so we can return a standard 429 envelope (not an SSE event).

    Best-effort if Redis is unavailable: log + skip (matches runtime).
    """
    limits = default_limits_from_config()
    try:
        await check_and_consume(
            redis=redis_client,
            actor_kind=actor.kind,
            actor_id=actor.id,
            workspace_id=actor.workspace_id,
            limits=limits,
        )
    except RateLimitExceeded:
        # Bubble — the chat endpoint converts this to a 429 envelope.
        raise
    except Exception:  # noqa: BLE001 — Redis outage should not block invocation
        logger.warning("rate-limit pre-flight skipped (redis unavailable)", exc_info=True)


async def _chat_event_generator(
    req: InvokeRequest,
    db: AsyncSession,
):
    """Async generator that yields raw SSE-encoded strings.

    - Wraps :func:`runtime_stream` and assigns sequential ``event_id``s.
    - Persists every event into the per-session Redis stream for reconnect.
    - Inserts ``event: ping`` heartbeats every 25 s of idle.
    - Converts mid-stream runtime exceptions into ``error`` + ``done`` events
      so the HTTP status stays 200.
    - Always finishes by setting the Redis stream's TTL via finalize_stream.
    """
    event_id = 0
    session_id_for_log: UUID | str | None = None
    saw_done = False

    async def _emit(kind: str, payload: dict) -> str:
        """Persist + format one event. Bumps ``event_id``."""
        nonlocal event_id, session_id_for_log, saw_done
        current_id = event_id
        event_id += 1
        if session_id_for_log is not None:
            await agent_event_log_service.append_event(
                redis_client, session_id_for_log, current_id, kind, payload
            )
        if kind == "done":
            saw_done = True
        return _format_sse(kind, current_id, payload)

    runtime_iter = runtime_stream(req, db=db).__aiter__()
    # We must NOT use ``asyncio.wait_for(runtime_iter.__anext__(), timeout=...)``
    # — it cancels the awaited coroutine on timeout, which pulls the rug out
    # from under runtime_stream() right in the middle of an LLM call. The
    # whole graph then unwinds with CancelledError and the user gets nothing.
    # Instead we keep one long-lived ``pending_next`` task and shield it from
    # the per-tick timeout. When a tick times out we just emit a ping and
    # loop — the same pending_next task continues running in the background.
    pending_next: asyncio.Task | None = None

    try:
        while True:
            if pending_next is None:
                pending_next = asyncio.ensure_future(runtime_iter.__anext__())

            try:
                ev = await asyncio.wait_for(
                    asyncio.shield(pending_next),
                    timeout=_HEARTBEAT_INTERVAL_SECONDS,
                )
                pending_next = None  # consumed; next loop will start a new one
            except StopAsyncIteration:
                pending_next = None
                break
            except TimeoutError:
                # No event for 25s — emit a heartbeat. The shielded
                # pending_next task keeps running in the background; we'll
                # await it again on the next tick.
                ping_id = event_id
                event_id += 1
                yield _format_sse("ping", ping_id, {})
                continue

            # The first event from runtime is always 'session' — capture id.
            if ev.kind == "session" and session_id_for_log is None:
                raw = ev.payload.get("session_id")
                if raw is not None:
                    try:
                        session_id_for_log = UUID(str(raw))
                    except (TypeError, ValueError):
                        session_id_for_log = str(raw)

            yield await _emit(ev.kind, dict(ev.payload))

    except (BudgetExhausted, TurnLimitReached, ContextOverflow) as exc:
        code_map = {
            "BudgetExhausted": "budget_exhausted",
            "TurnLimitReached": "turn_limit_reached",
            "ContextOverflow": "context_overflow",
        }
        yield await _emit(
            "error",
            {"code": code_map[type(exc).__name__], "message": str(exc)},
        )
    except AgentError as exc:
        yield await _emit("error", {"code": "agent_error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001 — surface unknown failures cleanly
        logger.exception("chat: unexpected error in SSE generator: %s", exc)
        yield await _emit("error", {"code": "internal_error", "message": str(exc)})
    finally:
        # Cancel any in-flight pending_next so we don't leak the task when the
        # generator exits early (client disconnect, exception, etc).
        if pending_next is not None and not pending_next.done():
            pending_next.cancel()
            with contextlib.suppress(BaseException):
                await pending_next

        # Always close the runtime iterator so DB sessions / generators clean up.
        aclose = getattr(runtime_iter, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001 — never let cleanup mask the response
                logger.debug("chat: runtime aclose raised", exc_info=True)

        # Guarantee a terminal `done` even if runtime was cut off mid-flight
        # (e.g. an unexpected exception path that already yielded `error` but
        # not `done`).
        if not saw_done:
            yield await _emit(
                "done",
                {"session_id": str(session_id_for_log) if session_id_for_log else None},
            )

        # Set TTL on the Redis replay log so reconnects within 5 min still work.
        if session_id_for_log is not None:
            await agent_event_log_service.finalize_stream(
                redis_client, session_id_for_log
            )


@router.post("/{agent_id}/chat")
async def chat_agent(
    agent_id: str,
    body: InvokeBody,
    actor: ActorRef = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Streaming chat endpoint. Yields events from :func:`runtime.stream`.

    Wire format per spec §5.4::

        event: <kind>
        id: <sequential int>
        data: <json payload>
        \\n\\n

    First event is always ``session``, last is always ``done``.  Errors that
    surface mid-stream are encoded as ``event: error`` followed by
    ``event: done`` (HTTP status remains 200).  Pre-stream errors (auth,
    rate-limit) return a standard JSON error envelope with the appropriate
    4xx status — the SSE protocol never starts.

    Heartbeat: ``event: ping`` every 25 s of idle (per §3.7).
    """
    # ── 1. Pre-flight rate-limit check (so 429 is a normal HTTP error, not SSE).
    try:
        await _rate_limit_preflight(actor, db, agent_id)
    except RateLimitExceeded as exc:
        return _error_response(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="rate_limited",
            message=str(exc),
            agent_id=agent_id,
            details={"scope": str(exc.scope), "limit": exc.limit},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    # ── 2. Build InvokeRequest from body. ────────────────────────────────────
    chat_ctx = ChatContext(
        kind=body.context.kind,
        id=body.context.id,
        draft_id=body.context.draft_id,
        parent_diagram_id=body.context.parent_diagram_id,
    )
    req = InvokeRequest(
        agent_id=agent_id,
        actor=actor,
        workspace_id=actor.workspace_id,
        chat_context=chat_ctx,
        message=body.message,
        mode=body.mode,
        session_id=body.session_id,
        metadata=body.metadata,
    )

    # ── 3. Return the streaming response. ────────────────────────────────────
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _chat_event_generator(req, db),
        media_type="text/event-stream",
        headers=headers,
    )
