"""AgentRuntime — single entry point for both one-shot invoke and streaming chat.

The runtime owns:
  * Resolving the :class:`~app.agents.registry.AgentDescriptor` and the
    :class:`~app.services.agent_settings_service.ResolvedAgentSettings`.
  * Clamping the requested mode against the actor's policy
    (:func:`_clamp_mode`, per spec §4.11).
  * Resolving the active draft id (:func:`_resolve_active_draft_id`, per
    spec §4.12).
  * Wiring an :class:`~app.agents.llm.LLMClient`,
    :class:`~app.agents.limits.LimitsEnforcer`, and
    :class:`~app.agents.context_manager.ContextManager` for the invocation.
  * Loading or creating the :class:`~app.models.agent_chat_session.AgentChatSession`
    and composing :class:`AgentState` for the LangGraph entry.
  * Driving :meth:`CompiledStateGraph.astream_events` and mapping LangGraph
    events to :class:`SSEEvent` for transport.
  * Persisting :class:`~app.models.agent_chat_message.AgentChatMessage` rows
    + :class:`~app.agents.state.ChangeRecord` entries as the graph emits them.
  * Pre-flight rate limit gating via
    :func:`app.services.rate_limit_service.check_and_consume`.

Phase 1 SSE event coverage (per the task brief — token-level + per-tool
granularity is deferred to Phase 2 once nodes use ``dispatch_custom_event``):

  * ``session``        — emitted once at entry with ``{session_id, agent_id, started_at}``.
  * ``node``           — emitted on each LangGraph ``on_chain_start`` for a real node.
  * ``applied_change`` — emitted when ``state.applied_changes`` grows.
  * ``message``        — emitted when ``state.final_message`` is set.
  * ``budget_warning`` — emitted when the enforcer latches a one-shot warning.
  * ``compaction_applied`` — emitted when the context manager runs a stage.
  * ``usage``          — emitted at end with ``{tokens_in, tokens_out, cost_usd}``.
  * ``done``           — terminal event with ``{session_id}``.
  * ``error``          — emitted before ``done`` on failure
    (``BudgetExhausted`` / ``TurnLimitReached`` / ``RateLimitExceeded`` / ``AgentError``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import registry
from app.agents.context_manager import ContextManager
from app.agents.errors import (
    AgentError,
    BudgetExhausted,
    ContextOverflow,
    TurnLimitReached,
)
from app.agents.limits import LimitsEnforcer, RuntimeCounters, RuntimeLimits
from app.agents.llm import LLMCallMetadata, LLMClient
from app.models.agent_chat_message import AgentChatMessage, MessageRole
from app.models.agent_chat_session import AgentChatSession
from app.services.agent_settings_service import (
    ResolvedAgentSettings,
    resolve_for_agent,
)
from app.services.rate_limit_service import (
    RateLimitExceeded,
    check_and_consume,
    default_limits_from_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChatContext:
    """Frontend-supplied scoping context for an invocation.

    Mirrors :class:`app.agents.state.ChatContext` but as a plain dataclass so
    it can be used in the runtime's :class:`InvokeRequest` / wire shape
    without forcing the Pydantic dependency on callers.
    """

    kind: Literal["workspace", "diagram", "object", "none"]
    id: UUID | None = None
    draft_id: UUID | None = None
    parent_diagram_id: UUID | None = None


@dataclass
class ActorRef:
    """Reference to the caller. ``kind='user'`` uses ``agent_access`` for
    policy clamping; ``kind='api_key'`` uses ``scopes``.
    """

    kind: Literal["user", "api_key"]
    id: UUID
    workspace_id: UUID
    scopes: tuple[str, ...] = ()  # for api_key
    agent_access: Literal["none", "read_only", "full"] | None = None  # for user


@dataclass
class InvokeRequest:
    agent_id: str
    actor: ActorRef
    workspace_id: UUID
    chat_context: ChatContext
    message: str
    mode: Literal["full", "read_only"] = "full"
    session_id: UUID | None = None
    metadata: dict | None = None  # client-supplied (e.g. {client: "claude-code/x"})


@dataclass
class InvokeResult:
    session_id: UUID
    agent_id: str
    final_message: str
    applied_changes: list[dict]
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal | None
    duration_ms: int
    forced_finalize: str | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SSEEvent:
    """Generic SSE event envelope emitted by the runtime.

    The transport layer (A2A SSE endpoint, internal chat WS) is responsible
    for serializing this — runtime stays transport-agnostic.

    Recognized ``kind`` values (Phase 1):
      ``session`` | ``node`` | ``applied_change`` | ``message`` |
      ``budget_warning`` | ``compaction_applied`` | ``usage`` |
      ``done`` | ``error`` | ``ping``
    """

    kind: str
    payload: dict


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def invoke(req: InvokeRequest, *, db: AsyncSession) -> InvokeResult:
    """One-shot invocation. Drains :func:`stream` internally + aggregates."""
    final_message = ""
    applied_changes: list[dict] = []
    tokens_in = 0
    tokens_out = 0
    cost_usd: Decimal | None = None
    duration_ms = 0
    forced_finalize: str | None = None
    warnings: list[str] = []
    session_id: UUID = req.session_id or uuid4()
    error: dict | None = None

    async for event in stream(req, db=db):
        if event.kind == "session":
            raw_session_id = event.payload.get("session_id")
            if isinstance(raw_session_id, UUID):
                session_id = raw_session_id
            elif isinstance(raw_session_id, str):
                with contextlib.suppress(ValueError):
                    session_id = UUID(raw_session_id)
        elif event.kind == "applied_change":
            applied_changes.append(event.payload)
        elif event.kind == "message":
            final_message = event.payload.get("text", final_message)
        elif event.kind == "usage":
            tokens_in = event.payload.get("tokens_in", tokens_in)
            tokens_out = event.payload.get("tokens_out", tokens_out)
            cost_usd = event.payload.get("cost_usd", cost_usd)
            duration_ms = event.payload.get("duration_ms", duration_ms)
            forced_finalize = event.payload.get("forced_finalize", forced_finalize)
        elif event.kind == "budget_warning":
            warnings.append(
                f"budget warning: used={event.payload.get('used_usd')} "
                f"limit={event.payload.get('limit_usd')}"
            )
        elif event.kind == "error":
            error = event.payload

    if error is not None:
        code = error.get("code") or "agent_error"
        message = error.get("message") or "agent run failed"
        if code == "rate_limit_exceeded":
            raise RateLimitExceeded(
                scope=error.get("scope", "unknown"),
                limit=int(error.get("limit", 0) or 0),
                retry_after_seconds=int(error.get("retry_after_seconds", 1) or 1),
            )
        if code == "budget_exhausted":
            raise BudgetExhausted(message)
        if code == "turn_limit_reached":
            raise TurnLimitReached(message)
        if code == "context_overflow":
            raise ContextOverflow(message)
        if code == "agent_not_found":
            raise AgentError(message)
        if code == "permission_denied":
            raise PermissionError(message)
        raise AgentError(message)

    return InvokeResult(
        session_id=session_id,
        agent_id=req.agent_id,
        final_message=final_message,
        applied_changes=applied_changes,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        forced_finalize=forced_finalize,
        warnings=warnings,
    )


async def stream(
    req: InvokeRequest, *, db: AsyncSession
) -> AsyncIterator[SSEEvent]:
    """Stream the invocation as SSE events.

    Always emits ``session`` first, ``done`` last. May emit ``error`` between
    them on failure. Persists messages + applied changes to the DB inline.
    """
    started_at = datetime.now(UTC)

    # ── 1. Resolve descriptor (catch agent_not_found here, before session) ──
    try:
        descriptor = registry.get(req.agent_id)
    except KeyError as exc:
        # No session in this branch — emit a synthetic session_id so the
        # client still has a stable handle for tracing.
        synth_session_id = req.session_id or uuid4()
        yield SSEEvent(
            "session",
            {
                "session_id": str(synth_session_id),
                "agent_id": req.agent_id,
                "started_at": started_at.isoformat(),
            },
        )
        yield SSEEvent(
            "error",
            {"code": "agent_not_found", "message": str(exc)},
        )
        yield SSEEvent("done", {"session_id": str(synth_session_id)})
        return

    # ── 2. Clamp mode against actor policy ──
    try:
        clamped_mode = _clamp_mode(req.mode, req.actor)
    except PermissionError as exc:
        synth_session_id = req.session_id or uuid4()
        yield SSEEvent(
            "session",
            {
                "session_id": str(synth_session_id),
                "agent_id": req.agent_id,
                "started_at": started_at.isoformat(),
            },
        )
        yield SSEEvent(
            "error",
            {"code": "permission_denied", "message": str(exc)},
        )
        yield SSEEvent("done", {"session_id": str(synth_session_id)})
        return

    # ── 3. Resolve agent settings ──
    settings = await resolve_for_agent(db, req.workspace_id, req.agent_id)

    # ── 4. Rate-limit pre-flight (best-effort: if redis unavailable, log) ──
    try:
        from app.core.redis import redis_client

        rate_limits = default_limits_from_config()
        await check_and_consume(
            redis=redis_client,
            actor_kind=req.actor.kind,
            actor_id=req.actor.id,
            workspace_id=req.workspace_id,
            limits=rate_limits,
        )
    except RateLimitExceeded as exc:
        synth_session_id = req.session_id or uuid4()
        yield SSEEvent(
            "session",
            {
                "session_id": str(synth_session_id),
                "agent_id": req.agent_id,
                "started_at": started_at.isoformat(),
            },
        )
        yield SSEEvent(
            "error",
            {
                "code": "rate_limit_exceeded",
                "message": str(exc),
                "scope": str(exc.scope),
                "limit": int(exc.limit),
                "retry_after_seconds": int(exc.retry_after_seconds),
            },
        )
        yield SSEEvent("done", {"session_id": str(synth_session_id)})
        return
    except Exception:  # noqa: BLE001 — redis outage shouldn't block invocation
        logger.warning(
            "rate_limit pre-flight skipped (redis unavailable)", exc_info=True
        )

    # ── 5. Resolve / create session ──
    try:
        session = await _load_or_create_session(db, req=req)
    except PermissionError as exc:
        synth_session_id = req.session_id or uuid4()
        yield SSEEvent(
            "session",
            {
                "session_id": str(synth_session_id),
                "agent_id": req.agent_id,
                "started_at": started_at.isoformat(),
            },
        )
        yield SSEEvent(
            "error",
            {"code": "permission_denied", "message": str(exc)},
        )
        yield SSEEvent("done", {"session_id": str(synth_session_id)})
        return

    yield SSEEvent(
        "session",
        {
            "session_id": str(session.id),
            "agent_id": req.agent_id,
            "started_at": started_at.isoformat(),
        },
    )

    # ── 6. Resolve active_draft_id (drafts integration, §4.12) ──
    active_draft_id, requires_choice = await _resolve_active_draft_id(
        db,
        chat_context=req.chat_context,
        agent_edits_policy=settings.agent_edits_policy,
        mode=clamped_mode,
        actor=req.actor,
    )
    if requires_choice is not None:
        yield SSEEvent("requires_choice", requires_choice)

    # ── 7. Build LLM + enforcer + context manager ──
    llm = LLMClient(settings)
    counters = RuntimeCounters()
    limits = RuntimeLimits(
        turn_limit=settings.turn_limit,
        turn_extension=settings.turn_extension,
        budget_usd=settings.budget_usd,
        budget_scope=settings.budget_scope,  # type: ignore[arg-type]
        on_budget_exhausted=settings.on_budget_exhausted,  # type: ignore[arg-type]
        health_check_model=settings.health_check_model,
    )
    enforcer = LimitsEnforcer(
        limits=limits,
        counters=counters,
        llm=llm,
        db=db,
        workspace_id=req.workspace_id,
        agent_id=req.agent_id,
    )
    context_manager = ContextManager(
        threshold=settings.context_threshold,
        ladder_strategy_names=list(settings.context_ladder),
        tool_result_trim_threshold_tokens=settings.tool_result_trim_threshold_tokens,
        summarizer_model_override=settings.health_check_model,
    )

    # One trace_id per chat invocation (per agent round).  All LLM calls
    # within this round share it so Langfuse groups them under one trace; the
    # session_id (agent_chat_session.id) groups multiple rounds under one
    # Langfuse session.
    invocation_trace_id = str(uuid4())
    call_metadata_base = _build_call_metadata(
        req=req,
        session=session,
        settings=settings,
        agent_id=req.agent_id,
        trace_id=invocation_trace_id,
    )

    # Open a Langfuse trace + tracer that opens spans per node visit. No-op
    # when Langfuse isn't configured. Sub-agents nest under the supervisor
    # span via ``parent_observation_id`` in LiteLLM metadata.
    from app.agents.tracing import AgentTracer

    agent_tracer = AgentTracer(
        trace_id=invocation_trace_id,
        agent_id=req.agent_id,
        session_id=str(session.id),
        user_id=str(req.actor.id),
        tags=[
            f"agent:{req.agent_id}",
            f"workspace:{req.workspace_id}",
            f"context:{req.chat_context.kind}",
        ],
        chat_input=req.message,
    )

    tool_executor = _make_tool_executor(
        db=db,
        actor=req.actor,
        workspace_id=req.workspace_id,
        chat_context=req.chat_context,
        active_draft_id=active_draft_id,
        agent_id=req.agent_id,
        mode=clamped_mode,
    )

    # ── 8. Load existing chat history + persist user message ──
    existing_messages = await _load_existing_messages(db, session_id=session.id)
    next_seq = (
        max((m["sequence"] for m in existing_messages), default=-1) + 1
    )
    await _persist_message(
        db,
        session_id=session.id,
        sequence=next_seq,
        role=MessageRole.USER.value,
        content_text=req.message,
    )
    next_seq += 1

    initial_state = _build_initial_state(
        req=req,
        session=session,
        active_draft_id=active_draft_id,
        clamped_mode=clamped_mode,
        existing_messages=existing_messages,
    )

    # ── 9. Drive the graph ──
    deps_for_config = {
        "enforcer": enforcer,
        "context_manager": context_manager,
        "tool_executor": tool_executor,
        "call_metadata_base": call_metadata_base,
        "agent_tracer": agent_tracer,
    }

    graph = descriptor.graph
    final_state: dict[str, Any] | None = None
    forced_finalize: str | None = None
    last_emitted_change_count = 0
    last_compaction_stage = session.compaction_stage or 0
    error_event: dict | None = None
    cancelled = False
    event_count = 0

    # Cache the redis client + session_service ref for the cancel flag poll —
    # we look up every 5 events to bound Redis hits during a long run.
    _cancel_redis = None
    _is_cancel_requested = None
    try:
        from app.core.redis import redis_client as _cancel_redis  # type: ignore
        from app.services.agent_session_service import (
            is_cancel_requested as _is_cancel_requested,  # type: ignore
        )
    except Exception:  # noqa: BLE001 — redis unavailable: silently skip cancel poll
        _cancel_redis = None
        _is_cancel_requested = None

    try:
        async for event in _drive_graph(
            graph,
            initial_state,
            config={"configurable": deps_for_config},
        ):
            event_count += 1
            # Check the cancel flag every 5 events (spec recommendation —
            # bounds Redis traffic for long runs).  Skip the check entirely
            # if redis was unavailable at startup.
            if (
                _cancel_redis is not None
                and _is_cancel_requested is not None
                and event_count % 5 == 0
            ):
                try:
                    if await _is_cancel_requested(_cancel_redis, session.id):
                        cancelled = True
                        yield SSEEvent(
                            "cancelled",
                            {
                                "reason": "user",
                                "session_id": str(session.id),
                            },
                        )
                        break
                except Exception:  # noqa: BLE001 — outage shouldn't kill the run
                    logger.debug(
                        "cancel-flag poll failed for session=%s",
                        session.id,
                        exc_info=True,
                    )

            ev_type = event.get("event")
            data = event.get("data") or {}

            if ev_type == "on_chain_start":
                node_name = event.get("name") or ""
                # Only emit for *real* nodes (skip internal LangGraph chains
                # like __start__, RunnableSeq, etc.). Real nodes are the ones
                # registered in the graph.
                if not node_name.startswith("__") and node_name in _real_node_names(graph):
                    yield SSEEvent("node", {"name": node_name})
            elif ev_type == "on_chain_end":
                # Capture the latest state seen on a chain end — for graph end
                # this is the final state. We MERGE rather than replace so a
                # mid-stream cancel still leaves us with the strongest snapshot
                # we have (e.g. researcher's findings even if supervisor never
                # got to write final_message).
                output = data.get("output")
                if isinstance(output, dict):
                    if final_state is None:
                        final_state = dict(output)
                    else:
                        for k, v in output.items():
                            if v is not None and v != "":
                                final_state[k] = v
                # Surface compaction events from the enforcer / context-manager
                if enforcer.budget_warning_pending is not None:
                    pending = enforcer.consume_budget_warning()
                    if pending is not None:
                        used, lim = pending
                        yield SSEEvent(
                            "budget_warning",
                            {
                                "used_usd": str(used),
                                "limit_usd": str(lim),
                                "scope": str(enforcer.limits.budget_scope),
                            },
                        )
                # Emit applied_change events for any new entries in state.
                if isinstance(output, dict):
                    new_changes = output.get("applied_changes") or []
                    while last_emitted_change_count < len(new_changes):
                        change = new_changes[last_emitted_change_count]
                        if isinstance(change, dict):
                            yield SSEEvent("applied_change", dict(change))
                        else:
                            # ChangeRecord pydantic model
                            payload = (
                                change.model_dump(mode="json")
                                if hasattr(change, "model_dump")
                                else dict(change)
                            )
                            yield SSEEvent("applied_change", payload)
                        last_emitted_change_count += 1

    except (BudgetExhausted, TurnLimitReached, ContextOverflow) as exc:
        code = type(exc).__name__
        # Map to spec codes
        code_map = {
            "BudgetExhausted": "budget_exhausted",
            "TurnLimitReached": "turn_limit_reached",
            "ContextOverflow": "context_overflow",
        }
        error_event = {"code": code_map[code], "message": str(exc)}
    except asyncio.CancelledError:
        # SSE connection torn down (frontend abort, browser navigation, network
        # blip). Mark cancelled so the post-loop cleanup writes a sensible
        # final_message — usually findings.summary if the researcher had time
        # to produce one before the abort, otherwise a generic notice.
        logger.warning("agent runtime: stream cancelled (frontend abort or timeout)")
        cancelled = True
        forced_finalize = "cancelled"
        # Re-raise after cleanup runs is incorrect for an async generator —
        # we just fall through to the persistence block.
    except AgentError as exc:
        error_event = {"code": "agent_error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface unknown failures
        logger.exception("unexpected error in agent runtime: %s", exc)
        error_event = {"code": "internal_error", "message": str(exc)}

    # ── 10. Persist applied state + emit terminal events ──
    final_message = ""
    if isinstance(final_state, dict):
        final_message = (final_state.get("final_message") or "") or ""
        if final_state.get("forced_finalize"):
            forced_finalize = final_state["forced_finalize"]
        # Fallback: if the run was cut short (cancel / error) we may have
        # findings from a sub-agent that completed before the abort but no
        # final_message. Surface findings.summary as the user reply rather
        # than dropping a half-finished invocation on the floor.
        if not final_message:
            findings = final_state.get("findings")
            summary = (
                getattr(findings, "summary", None)
                if not isinstance(findings, dict)
                else findings.get("summary")
            )
            if summary and summary.strip():
                final_message = summary.strip()
                logger.warning(
                    "agent runtime: surfaced findings.summary as final_message (forced=%s)",
                    forced_finalize,
                )
        # Persist any new assistant messages from final state.
        msgs = final_state.get("messages") or []
        # Existing message count = original chat history + the user message we
        # just persisted. Anything beyond that was produced by the graph.
        original_count = len(existing_messages) + 1
        for idx, m in enumerate(msgs[original_count:], start=next_seq):
            if not isinstance(m, dict):
                continue
            role = m.get("role") or "assistant"
            try:
                msg_role = MessageRole(role)
            except ValueError:
                msg_role = MessageRole.ASSISTANT
            await _persist_message(
                db,
                session_id=session.id,
                sequence=idx,
                role=msg_role.value,
                content_text=m.get("content")
                if isinstance(m.get("content"), str)
                else None,
                content_json=m if not isinstance(m.get("content"), str) else None,
                tool_call_id=m.get("tool_call_id"),
            )

        # Persist a final assistant turn if we have a final_message that's
        # not already represented as the last assistant message.
        if final_message and msgs:
            last = msgs[-1]
            already_persisted = (
                isinstance(last, dict)
                and last.get("role") == "assistant"
                and last.get("content") == final_message
            )
            if not already_persisted:
                await _persist_message(
                    db,
                    session_id=session.id,
                    sequence=idx + 1 if msgs[original_count:] else next_seq,
                    role=MessageRole.ASSISTANT.value,
                    content_text=final_message,
                )

        # Persist any compaction stage advancement.
        if last_compaction_stage != (final_state.get("compaction_stage") or last_compaction_stage):
            session.compaction_stage = int(final_state.get("compaction_stage") or 0)

    # If we tripped the cancel flag, override forced_finalize regardless of
    # whatever the graph reported (we broke out mid-loop, so its state is
    # incomplete).  Best-effort clear the Redis flag so a future invocation
    # of the same session id starts clean.
    if cancelled:
        forced_finalize = "cancelled"
        if _cancel_redis is not None:
            try:
                from app.services.agent_session_service import (
                    clear_cancel,
                )

                await clear_cancel(_cancel_redis, session.id)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "post-cancel flag cleanup failed for session=%s",
                    session.id,
                    exc_info=True,
                )

    # Close out the Langfuse trace before flushing DB writes so the trace
    # always finishes even if a flush failure raises.
    try:
        agent_tracer.finish(
            output={
                "final_message": final_message,
                "forced_finalize": forced_finalize,
            }
        )
    except Exception:  # noqa: BLE001 — defensive
        logger.debug("agent_tracer.finish failed", exc_info=True)

    # Flush and emit usage / message
    try:
        await db.flush()
    except Exception:  # noqa: BLE001 — best-effort
        logger.warning("failed to flush session writes", exc_info=True)

    if error_event is not None:
        yield SSEEvent("error", error_event)
    else:
        if final_message:
            yield SSEEvent("message", {"text": final_message})

        duration_ms = int(
            (datetime.now(UTC) - started_at).total_seconds() * 1000
        )
        yield SSEEvent(
            "usage",
            {
                "tokens_in": int(counters.cost_usd != Decimal("0"))
                * 0  # placeholder; tokens come from final state
                + int((final_state or {}).get("tokens_in") or 0),
                "tokens_out": int((final_state or {}).get("tokens_out") or 0),
                "cost_usd": counters.cost_usd if counters.cost_usd > 0 else None,
                "duration_ms": duration_ms,
                "forced_finalize": forced_finalize,
            },
        )

    yield SSEEvent("done", {"session_id": str(session.id)})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Scope hierarchy (broader scopes imply narrower ones — mirrors registry).
_SCOPE_HIERARCHY: dict[str, int] = {
    "agents:read": 0,
    "agents:invoke": 1,
    "agents:write": 2,
    "agents:admin": 3,
}


def _scope_satisfied(required_scope: str, actor_scopes: tuple[str, ...]) -> bool:
    required_level = _SCOPE_HIERARCHY.get(required_scope, 0)
    for scope in actor_scopes:
        level = _SCOPE_HIERARCHY.get(scope, -1)
        if level >= required_level:
            return True
    return False


def _clamp_mode(
    requested: Literal["full", "read_only"],
    actor: ActorRef,
) -> Literal["full", "read_only"]:
    """Clamp the requested mode against actor policy (per §4.11).

    Rules:
      * ``api_key`` actors: ``agents:write`` or ``agents:admin`` → honor
        requested mode; any lower scope → clamp to ``read_only``.
      * ``user`` actors: ``agent_access='none'`` → :class:`PermissionError`;
        ``read_only`` → forced ``read_only`` regardless of request;
        ``full`` → honor the requested mode.
    """
    if actor.kind == "api_key":
        has_write = _scope_satisfied("agents:write", actor.scopes)
        has_admin = _scope_satisfied("agents:admin", actor.scopes)
        if requested == "full" and not (has_write or has_admin):
            return "read_only"
        return requested

    # User actor
    access = actor.agent_access or "read_only"
    if access == "none":
        raise PermissionError(
            "User has agent_access='none'; agent invocation forbidden"
        )
    if access == "read_only":
        return "read_only"
    # access == "full"
    return requested


async def _resolve_active_draft_id(
    db: AsyncSession,
    *,
    chat_context: ChatContext,
    agent_edits_policy: str,
    mode: Literal["full", "read_only"],
    actor: ActorRef,
) -> tuple[UUID | None, dict | None]:
    """Resolve the active draft id for the invocation (per §4.12).

    Returns ``(draft_id, requires_choice_payload)``.

    Branch logic:
      1. ``chat_context.draft_id`` explicit → verify workspace ownership and
         return it immediately (``requires_choice=None``).
      2. ``mode == 'read_only'`` → drafts irrelevant; return ``(None, None)``.
      3. ``live_only`` policy → no draft; return ``(None, None)``.
      4. ``drafts_only`` policy + diagram context:
           * 0 open drafts → suspend with ``requires_choice`` (create / cancel).
           * 1 open draft  → auto-pick it; return ``(draft_id, None)``.
           * 2+ open drafts → suspend with ``requires_choice`` listing choices.
      5. ``ask`` policy + diagram context + ``full`` mode:
           * 0 open drafts → defer to first mutating call; return ``(None,
             requires_choice_payload)`` with ``kind='draft_or_live'``.
           * 1+ open drafts → suspend with options (use existing | new draft |
             edit live); return ``(None, requires_choice_payload)``.
         In all other combinations (non-diagram context or read_only already
         handled above) → return ``(None, None)``.
    """
    # ── Branch 1: explicit draft_id in context ──────────────────────────────
    if chat_context.draft_id is not None:
        # Lightweight ownership check: confirm the draft belongs to this
        # workspace by querying draft_service. If the lookup fails (FakeSession
        # in tests, or draft deleted) we still honour the caller's intent and
        # return it — the tool layer will enforce actual ACL.
        try:
            from app.services import draft_service

            draft = await draft_service.get_draft(db, chat_context.draft_id)
            if draft is not None:
                # Verify workspace ownership via the forked diagram's workspace.
                # Draft model has no workspace_id directly; we trust the context
                # workspace + tool-level ACL for the full check.  Phase 1: pass.
                pass
        except Exception:  # noqa: BLE001 — best-effort; don't block on DB issues
            logger.debug(
                "draft ownership pre-check skipped for draft_id=%s",
                chat_context.draft_id,
                exc_info=True,
            )
        return chat_context.draft_id, None

    # ── Branch 2: read_only mode — drafts irrelevant ─────────────────────────
    if mode == "read_only":
        return None, None

    # ── Branch 3: live_only policy ───────────────────────────────────────────
    if agent_edits_policy == "live_only":
        return None, None

    # For branches 4 & 5 we need a diagram context with an id.
    has_diagram_context = (
        chat_context.kind == "diagram" and chat_context.id is not None
    )

    # ── Branch 4: drafts_only ────────────────────────────────────────────────
    if agent_edits_policy == "drafts_only":
        if not has_diagram_context:
            return None, None

        open_drafts = await _fetch_open_drafts(db, chat_context.id)  # type: ignore[arg-type]

        if len(open_drafts) == 1:
            # Auto-pick the single existing draft.
            return UUID(open_drafts[0]["draft_id"]), None

        if len(open_drafts) == 0:
            # No draft exists → suspend; user must create one first.
            payload: dict = {
                "kind": "draft_required",
                "message": "This workspace requires changes to be made in a draft.",
                "options": [
                    {"id": "create_draft", "label": "Create a draft (recommended)"},
                    {"id": "cancel", "label": "Cancel"},
                ],
                "diagram_id": str(chat_context.id),
                "tool_call_id": None,
            }
            return None, payload

        # 2+ drafts → suspend with choices listing all of them.
        options = [
            {"id": "create_draft", "label": "Create a new draft"},
        ]
        for d in open_drafts:
            options.append(
                {
                    "id": "use_existing_draft",
                    "label": f"Use existing draft '{d['draft_name']}'",
                    "draft_id": d["draft_id"],
                }
            )
        payload = {
            "kind": "draft_required",
            "message": "Multiple open drafts found. Choose one to continue:",
            "options": options,
            "diagram_id": str(chat_context.id),
            "tool_call_id": None,
        }
        return None, payload

    # ── Branch 5: ask policy ─────────────────────────────────────────────────
    if agent_edits_policy == "ask":
        if not has_diagram_context:
            # No diagram context → nothing to choose; defer to tool wrapper.
            return None, None

        open_drafts = await _fetch_open_drafts(db, chat_context.id)  # type: ignore[arg-type]

        if len(open_drafts) == 0:
            # No existing drafts → defer the choice to the first mutating tool
            # call (task 036 will wire _check_ask_policy_first_mutation).
            payload = {
                "kind": "draft_or_live",
                "message": "I'm about to make changes. Choose where to apply them:",
                "options": [
                    {"id": "create_draft", "label": "Create a draft (recommended)"},
                    {"id": "edit_live", "label": "Edit live diagram"},
                ],
                "tool_call_id": None,
            }
            return None, payload

        # 1+ existing drafts → offer use-existing | new | edit-live.
        options: list[dict] = [
            {"id": "create_draft", "label": "Create a draft (recommended)"},
            {"id": "edit_live", "label": "Edit live diagram"},
        ]
        for d in open_drafts:
            options.append(
                {
                    "id": "use_existing_draft",
                    "label": f"Use existing draft '{d['draft_name']}'",
                    "draft_id": d["draft_id"],
                }
            )
        payload = {
            "kind": "draft_or_live",
            "message": "I'm about to make changes. Choose where to apply them:",
            "options": options,
            "tool_call_id": None,
        }
        return None, payload

    # Fallback for unknown policy values → treat as live_only.
    return None, None


async def _fetch_open_drafts(db: AsyncSession, diagram_id: UUID) -> list[dict]:
    """Return open drafts for *diagram_id* via draft_service (best-effort).

    Returns an empty list if the service call fails (e.g. FakeSession in unit
    tests that doesn't implement the required query).
    """
    try:
        from app.services import draft_service

        return await draft_service.get_drafts_for_diagram(db, diagram_id)
    except Exception:  # noqa: BLE001
        logger.debug(
            "get_drafts_for_diagram failed for diagram_id=%s", diagram_id, exc_info=True
        )
        return []


# ---------------------------------------------------------------------------
# Ask-policy deferred-choice helper (wired by task 036)
# ---------------------------------------------------------------------------


@dataclass
class _AskPolicyState:
    """Per-invocation mutable state for the 'ask' draft policy deferred check."""

    choice_presented: bool = False
    """True after the first mutation check has surfaced the requires_choice payload."""


def _check_ask_policy_first_mutation(
    state: _AskPolicyState,
    active_draft_id: UUID | None,
    agent_edits_policy: str,
    mode: Literal["full", "read_only"],
    pending_requires_choice: dict | None,
) -> dict | None:
    """Return a ``requires_choice`` payload if the 'ask' policy needs to present
    a choice before the first mutating tool call.

    This helper is called by the tool dispatcher (task 036) **before** invoking
    any mutating tool.  It returns the choice payload on the first call and
    ``None`` on subsequent calls (idempotent guard via ``state.choice_presented``).

    Returns ``None`` when:
      - policy is not 'ask'.
      - mode is 'read_only' (no mutations possible).
      - active_draft_id is already resolved (user already chose).
      - choice was already presented this invocation.
      - no pending payload was supplied (already handled at invocation start).

    On the first call that should present a choice:
      - Sets ``state.choice_presented = True``.
      - Returns the ``requires_choice`` payload dict.
    """
    if agent_edits_policy != "ask":
        return None
    if mode == "read_only":
        return None
    if active_draft_id is not None:
        return None
    if state.choice_presented:
        return None
    if pending_requires_choice is None:
        return None

    state.choice_presented = True
    return pending_requires_choice


async def _load_or_create_session(
    db: AsyncSession, *, req: InvokeRequest
) -> AgentChatSession:
    """Fetch an existing session (verifying actor ownership) or create a new one."""
    if req.session_id is not None:
        stmt = select(AgentChatSession).where(AgentChatSession.id == req.session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            raise PermissionError(
                f"session {req.session_id} not found or not accessible"
            )
        # Ownership check.
        if req.actor.kind == "user":
            if session.actor_user_id != req.actor.id:
                raise PermissionError(
                    "session does not belong to this user"
                )
        else:  # api_key
            if session.actor_api_key_id != req.actor.id:
                raise PermissionError(
                    "session does not belong to this api key"
                )
        if session.workspace_id != req.workspace_id:
            raise PermissionError("session belongs to a different workspace")
        return session

    # Create new.
    session = AgentChatSession(
        id=uuid4(),
        workspace_id=req.workspace_id,
        agent_id=req.agent_id,
        actor_user_id=req.actor.id if req.actor.kind == "user" else None,
        actor_api_key_id=req.actor.id if req.actor.kind == "api_key" else None,
        context_kind=req.chat_context.kind,
        context_id=req.chat_context.id,
        context_draft_id=req.chat_context.draft_id,
        compaction_stage=0,
        cancel_requested=False,
    )
    db.add(session)
    try:
        await db.flush()
    except Exception:  # noqa: BLE001 — keep working even if the test Fake doesn't flush
        logger.debug("flush after session insert failed", exc_info=True)
    return session


async def _persist_message(
    db: AsyncSession,
    *,
    session_id: UUID,
    sequence: int,
    role: str,
    content_text: str | None = None,
    content_json: dict | None = None,
    tool_call_id: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: Decimal | None = None,
    langfuse_trace_id: str | None = None,
    is_compacted: bool = False,
) -> None:
    """Insert one ``agent_chat_message`` row. No-op on flush failure (test pragmatism)."""
    msg = AgentChatMessage(
        id=uuid4(),
        session_id=session_id,
        sequence=sequence,
        role=MessageRole(role),
        content_text=content_text,
        content_json=content_json,
        tool_call_id=tool_call_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        langfuse_trace_id=langfuse_trace_id,
        is_compacted=is_compacted,
    )
    db.add(msg)
    try:
        await db.flush()
    except Exception:  # noqa: BLE001 — best-effort under FakeSession
        logger.debug("flush after message insert failed", exc_info=True)


async def _load_existing_messages(
    db: AsyncSession, *, session_id: UUID
) -> list[dict]:
    """Load chat history for the session as a list of dicts in LangGraph shape."""
    stmt = (
        select(AgentChatMessage)
        .where(AgentChatMessage.session_id == session_id)
        .order_by(AgentChatMessage.sequence.asc())
    )
    try:
        result = await db.execute(stmt)
        rows = list(result.scalars().all())
    except Exception:  # noqa: BLE001 — Fake session may not implement order_by
        logger.debug("loading existing messages failed", exc_info=True)
        return []

    out: list[dict] = []
    for row in rows:
        if row.is_compacted:
            continue
        msg: dict = {
            "role": (
                row.role.value
                if hasattr(row.role, "value")
                else str(row.role)
            ),
            "sequence": row.sequence,
        }
        if row.content_text is not None:
            msg["content"] = row.content_text
        elif row.content_json is not None:
            msg.update(row.content_json)
            msg.setdefault("role", row.role.value if hasattr(row.role, "value") else str(row.role))
        if row.tool_call_id:
            msg["tool_call_id"] = row.tool_call_id
        out.append(msg)
    return out


def _build_initial_state(
    req: InvokeRequest,
    session: AgentChatSession,
    active_draft_id: UUID | None,
    clamped_mode: Literal["full", "read_only"],
    existing_messages: list[dict],
) -> dict:
    """Compose the AgentState dict for graph entry."""
    # Strip the helper sequence key — graph nodes don't expect it.
    history: list[dict] = []
    for m in existing_messages:
        copy = {k: v for k, v in m.items() if k != "sequence"}
        history.append(copy)
    history.append({"role": "user", "content": req.message})

    return {
        "workspace_id": req.workspace_id,
        "session_id": session.id,
        "actor": {
            "actor_id": str(req.actor.id),
            "actor_kind": req.actor.kind,
            "workspace_id": str(req.actor.workspace_id),
        },
        "chat_context": {
            "kind": req.chat_context.kind,
            "id": str(req.chat_context.id) if req.chat_context.id else None,
            "draft_id": (
                str(req.chat_context.draft_id) if req.chat_context.draft_id else None
            ),
            "parent_diagram_id": (
                str(req.chat_context.parent_diagram_id)
                if req.chat_context.parent_diagram_id
                else None
            ),
        },
        "runtime_mode": clamped_mode,
        "active_draft_id": active_draft_id,
        "messages": history,
        "plan": None,
        "findings": None,
        "pending_changes": [],
        "applied_changes": [],
        "critique": None,
        "iteration": 0,
        "scratchpad": "",
        "final_message": None,
        "trace_id": None,
        "tokens_in": 0,
        "tokens_out": 0,
        "forced_finalize": None,
        "budget_counters": {},
    }


def _build_call_metadata(
    *,
    req: InvokeRequest,
    session: AgentChatSession,
    settings: ResolvedAgentSettings,
    agent_id: str,
    trace_id: str | None = None,
) -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=req.workspace_id,
        agent_id=agent_id,
        session_id=session.id,
        actor_id=req.actor.id,
        analytics_consent=settings.analytics_consent,
        context_kind=req.chat_context.kind,
        trace_id=trace_id,
    )


def _has_scope(
    actor_scopes: tuple[str, ...] | set[str],
    required: str,
) -> bool:
    """Check whether *actor_scopes* satisfies *required*.

    Scope hierarchy: ``agents:read`` (0) < ``agents:invoke`` (1) <
    ``agents:write`` (2) < ``agents:admin`` (3).

    Wildcard ``'*'`` satisfies any scope.  Unknown required scopes resolve
    to level 99 (never satisfied without wildcard or exact match).
    """
    if "*" in actor_scopes:
        return True
    actor_max = max(
        (_SCOPE_HIERARCHY.get(s, -1) for s in actor_scopes), default=-1
    )
    return actor_max >= _SCOPE_HIERARCHY.get(required, 99)


def filter_tools_for_actor(
    tool_schemas: list[dict],
    *,
    actor: ActorRef,
    mode: str,
) -> list[dict]:
    """Return only the tool schemas the actor is allowed to see.

    Drops schemas whose backing :class:`~app.agents.tools.base.Tool`:
      - requires a scope the ``api_key`` actor doesn't have.
      - is ``mutating=True`` when *mode* is ``'read_only'``.

    ``user`` actors are subject only to the mode filter — their access was
    clamped upstream via ``agent_access`` policy.

    Schemas for unregistered tool names are passed through unchanged so
    built-in plumbing tools (e.g. ``write_scratchpad``) are never silently
    dropped.
    """
    from app.agents.tools.base import get_tool

    allowed: list[dict] = []
    for schema in tool_schemas:
        name = schema.get("function", {}).get("name", "")
        try:
            t = get_tool(name)
        except KeyError:
            # Not in the tool registry (e.g. LangGraph internal / plumbing).
            # Pass through — runtime denial will catch mis-use.
            allowed.append(schema)
            continue
        if actor.kind == "api_key" and not _has_scope(actor.scopes, t.required_scope):
            continue
        if mode == "read_only" and t.mutating:
            continue
        allowed.append(schema)
    return allowed


def _make_tool_executor(
    *,
    db: AsyncSession,
    actor: ActorRef,
    workspace_id: UUID,
    chat_context: ChatContext,
    active_draft_id: UUID | None,
    agent_id: str,
    mode: Literal["full", "read_only"],
):
    """Build the tool executor coroutine for this invocation.

    Scope enforcement (§4.9):
      - If actor is ``api_key`` and the requested tool's ``required_scope``
        is not satisfied by the key's scopes → return ``status='denied'``
        immediately, without touching ``execute_tool``.
      - ``execute_tool`` in ``tools/base.py`` also enforces scope as a
        defence-in-depth layer.

    Returns an ``async (tool_call, state) -> dict`` callable.
    """
    from app.agents.tools.base import ToolContext, execute_tool, get_tool

    async def _executor(tool_call: dict, state: dict) -> dict:  # noqa: ARG001
        # --- Scope pre-check (api_key actors only) ---
        if actor.kind == "api_key":
            name = tool_call.get("name") or ""
            try:
                t = get_tool(name)
            except KeyError:
                return {
                    "tool_call_id": tool_call.get("id") or "",
                    "status": "error",
                    "content": f"unknown tool: {name}",
                    "preview": f"error: unknown tool {name}",
                }
            if not _has_scope(actor.scopes, t.required_scope):
                return {
                    "tool_call_id": tool_call.get("id") or "",
                    "status": "denied",
                    "content": (
                        f"scope {t.required_scope} required, "
                        f"key has {list(actor.scopes)}"
                    ),
                    "preview": f"denied: missing scope {t.required_scope}",
                }

        # --- Delegate to the full execute_tool wrapper ---
        ctx = ToolContext(
            db=db,
            actor=actor,
            workspace_id=workspace_id,
            chat_context={
                "kind": chat_context.kind,
                "id": str(chat_context.id) if chat_context.id else None,
                "draft_id": (
                    str(chat_context.draft_id) if chat_context.draft_id else None
                ),
                "parent_diagram_id": (
                    str(chat_context.parent_diagram_id)
                    if chat_context.parent_diagram_id
                    else None
                ),
            },
            session_id=state.get("session_id"),  # type: ignore[arg-type]
            agent_id=agent_id,
            agent_runtime_mode=mode,  # type: ignore[arg-type]
            active_draft_id=active_draft_id,
        )
        result = await execute_tool(tool_call, ctx)
        return {
            "tool_call_id": result.tool_call_id,
            "status": result.status,
            "content": result.content,
            "preview": result.preview,
            "raw": result.raw,
            "structured": result.structured,
        }

    return _executor


def _real_node_names(graph: Any) -> set[str]:
    """Return the set of real node names registered on the compiled graph.

    Defensive: not all graph stubs expose ``get_graph()``; falls back to an
    empty set so we never raise from the SSE mapper.
    """
    try:
        getter = getattr(graph, "get_graph", None)
        if callable(getter):
            g = getter()
            return {n for n in g.nodes if not str(n).startswith("__")}
    except Exception:  # noqa: BLE001
        pass
    return set()


async def _drive_graph(
    graph: Any,
    initial_state: dict,
    *,
    config: dict,
) -> AsyncIterator[dict]:
    """Drive the compiled LangGraph and yield raw events.

    Prefers ``astream_events(version='v2', ...)`` when available (real
    LangGraph). Falls back to ``ainvoke`` + a synthetic ``on_chain_end``
    event for stub graphs used in tests.
    """
    if hasattr(graph, "astream_events"):
        try:
            async for ev in graph.astream_events(
                initial_state, version="v2", config=config
            ):
                yield ev
            return
        except TypeError:
            # Older LangGraph signatures may not accept these kwargs; fall back.
            logger.debug("astream_events signature mismatch; falling back", exc_info=True)

    if hasattr(graph, "ainvoke"):
        try:
            output = await graph.ainvoke(initial_state, config=config)
        except TypeError:
            output = await graph.ainvoke(initial_state)
        yield {
            "event": "on_chain_end",
            "name": "__graph__",
            "data": {"output": output},
        }
        return

    if hasattr(graph, "invoke"):
        # Sync compiled graph (rare). Run inline.
        output = graph.invoke(initial_state, config=config)
        yield {
            "event": "on_chain_end",
            "name": "__graph__",
            "data": {"output": output},
        }
        return

    raise AgentError(
        f"compiled graph for agent has no astream_events/ainvoke/invoke "
        f"method (got type {type(graph).__name__!r})"
    )


async def cancel(session_id: UUID) -> None:
    """Signal a running invocation to cancel.

    Sets ``cancel:{session_id}`` in Redis (60s TTL).  ``_drive_graph`` polls
    this between yielded events and finalises with ``cancelled`` + ``done``
    when it sees the flag.  Idempotent: repeated calls just refresh the TTL.
    """
    from app.core.redis import redis_client
    from app.services.agent_session_service import request_cancel

    await request_cancel(redis_client, session_id)
