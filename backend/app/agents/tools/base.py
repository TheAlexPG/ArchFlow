"""Tool wrapper: ACL + audit + projection + draft routing + confirmed-gate.

Every tool implementation in tools/{model,view,search,web_fetch,reasoning,drafts}_tools.py
registers via the :func:`tool` decorator (or by constructing :class:`Tool` directly +
calling :func:`register_tool`) and is executed via :func:`execute_tool`.

Spec: §4.1 Tool Contract, §4.8 Output projections, §4.10 Audit, §4.12 Drafts integration.
"""
from __future__ import annotations

import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.agents.errors import AgentError, ToolDenied
from app.agents.redaction import scrub_for_telemetry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


Permission = Literal[
    "",  # reasoning tools have no permission
    "workspace:read",
    "workspace:edit",
    "diagram:read",
    "diagram:edit",
    "diagram:manage",
]


@dataclass
class ToolContext:
    """Runtime context injected into every tool handler call."""

    db: Any  # AsyncSession — typed as Any to avoid SQLAlchemy import here
    actor: Any  # ActorRef (kind in {'user', 'api_key'})
    workspace_id: UUID
    chat_context: dict
    session_id: UUID
    agent_id: str
    agent_runtime_mode: Literal["full", "read_only"]
    active_draft_id: UUID | None = None
    draft_target_diagram_id: UUID | None = None
    # Destructive-op reviewer needs the calling agent's recent messages
    # (so it can judge whether the delete fits the agent's stated goal).
    # Populated by the runtime's tool executor wrapper. Optional so direct
    # service callers / tests don't have to fill it in.
    agent_messages: list[dict] | None = None
    # LLM client used by the destructive-op reviewer to call out for an
    # APPROVE / REJECT verdict. ``None`` disables review (defaults to
    # silent approve — what tests / scripts get).
    llm_client: Any | None = None
    # Pre-resolved call metadata for the reviewer's LLM call. Optional.
    call_metadata: Any | None = None


@dataclass
class Tool:
    """Descriptor for a single callable tool exposed to an agent node."""

    name: str
    description: str
    input_schema: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Awaitable[dict]]
    required_permission: Permission = ""
    # 'workspace' (use ctx.workspace_id) | 'diagram' (extract diagram_id from args)
    # | 'object' (extract object_id; resolve diagram via parent) | 'connection'
    # | 'none' (reasoning + workspace-scoped reads where ctx.workspace_id is enough).
    permission_target: str = "workspace"
    required_scope: str = "agents:invoke"
    mutating: bool = False
    deprecates_model: bool = False  # destructive delete — UI hint
    needs_confirmed_gate: bool = False  # for delete_*; first call without confirmed → preview

    def to_openai_schema(self) -> dict:
        """Return an OpenAI function-calling tool dict.

        Shape::

            {"type": "function",
             "function": {"name": ..., "description": ..., "parameters": <jsonschema>}}
        """
        params = self.input_schema.model_json_schema()
        # Strip Pydantic's title/$defs decoration to keep schemas tight.
        params.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_TOOLS: dict[str, Tool] = {}

# Scope hierarchy mirrors agents.registry / agents.runtime.
_SCOPE_HIERARCHY: dict[str, int] = {
    "agents:read": 0,
    "agents:invoke": 1,
    "agents:write": 2,
    "agents:admin": 3,
}


def register_tool(t: Tool) -> None:
    """Register a tool. Idempotent — overwrites on same name (test hot-reload)."""
    _TOOLS[t.name] = t


def get_tool(name: str) -> Tool:
    """Return the registered :class:`Tool`. Raises ``KeyError`` with a hint if missing."""
    if name not in _TOOLS:
        valid = sorted(_TOOLS.keys())
        raise KeyError(f"Tool {name!r} not registered. Available: {valid}")
    return _TOOLS[name]


def all_tools() -> list[Tool]:
    """Return all registered tools, sorted by name."""
    return sorted(_TOOLS.values(), key=lambda x: x.name)


def filter_tools(
    *,
    scope: str,
    mode: Literal["full", "read_only"],
) -> list[Tool]:
    """Tools the caller may see/use.

    - ``scope`` hierarchy: ``agents:read`` < ``invoke`` < ``write`` < ``admin``.
      Tool included only if its ``required_scope`` is satisfied by ``scope``.
    - ``mode='read_only'``: drops tools where ``mutating=True``.
    """
    caller_level = _SCOPE_HIERARCHY.get(scope, -1)
    out: list[Tool] = []
    for t in all_tools():
        required_level = _SCOPE_HIERARCHY.get(t.required_scope, 0)
        if caller_level < required_level:
            continue
        if mode == "read_only" and t.mutating:
            continue
        out.append(t)
    return out


def clear_tools() -> None:
    """Test helper. Empties the registry."""
    _TOOLS.clear()


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tool(
    *,
    name: str,
    description: str,
    input_schema: type[BaseModel],
    permission: Permission = "",
    permission_target: str = "workspace",
    required_scope: str = "agents:invoke",
    mutating: bool = False,
    deprecates_model: bool = False,
    needs_confirmed_gate: bool = False,
):
    """Decorator that wraps an ``async def fn(args, ctx) -> dict`` handler into a
    :class:`Tool` and registers it.

    Usage::

        class CreateObjectInput(BaseModel):
            name: str
            type: str

        @tool(name='create_object', description='...',
              input_schema=CreateObjectInput,
              permission='diagram:edit', permission_target='diagram',
              mutating=True)
        async def create_object(args: CreateObjectInput, ctx: ToolContext) -> dict:
            ...
    """

    def _wrap(handler: Callable[[BaseModel, ToolContext], Awaitable[dict]]) -> Tool:
        t = Tool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            required_permission=permission,
            permission_target=permission_target,
            required_scope=required_scope,
            mutating=mutating,
            deprecates_model=deprecates_model,
            needs_confirmed_gate=needs_confirmed_gate,
        )
        register_tool(t)
        return t

    return _wrap


# ---------------------------------------------------------------------------
# Execution wrapper
# ---------------------------------------------------------------------------


@dataclass
class ToolExecutionResult:
    """What :func:`execute_tool` returns for the runtime to relay to the LLM."""

    tool_call_id: str
    name: str
    status: Literal["ok", "error", "denied", "awaiting_confirmation"]
    content: str  # JSON-encoded for LLM consumption
    preview: str  # short single-line preview for SSE/UI
    raw: dict = field(default_factory=dict)  # full result for storage in agent_chat_message
    structured: dict = field(default_factory=dict)  # parsed action/target_id for applied_changes


async def execute_tool(call: dict, ctx: ToolContext) -> ToolExecutionResult:
    """Generic tool execution flow.

    Steps (per spec §4.1):
      1. Parse call ``{id, name, arguments}``.
      2. Resolve tool by name; scope check (api_key actors only).
      3. Validate args via Pydantic.
      4. ACL check via :mod:`app.services.access_service`.
      5. Mode guard (``read_only`` blocks ``mutating=True``).
      6. Drafts routing: swap ``diagram_id`` → ``ctx.active_draft_id`` for mutating tools.
      7. Confirmed gate (handler-side; the wrapper just forwards ``args.confirmed``).
      8. Call handler.
      9. Project output for LLM (telemetry-grade redaction).
     10. Audit-log if mutating.
     11. Build :class:`ToolExecutionResult`.
    """
    tool_call_id = str(call.get("id") or "")
    name = call.get("name") or ""

    # ── 1. Parse arguments ────────────────────────────────────────
    raw_args = call.get("arguments")
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError as exc:
            return _err_result(
                tool_call_id, name,
                f"invalid arguments JSON: {exc.msg}",
            )
    elif raw_args is None:
        raw_args = {}
    elif not isinstance(raw_args, dict):
        return _err_result(tool_call_id, name, "arguments must be an object")

    # ── 2. Resolve tool ───────────────────────────────────────────
    try:
        t = get_tool(name)
    except KeyError:
        return _err_result(tool_call_id, name, f"tool not registered: {name}")

    # Scope filtering — only api_key actors carry scopes; user actors are clamped
    # earlier in the runtime via per-user policy.
    actor = ctx.actor
    if getattr(actor, "kind", None) == "api_key":
        scopes = tuple(getattr(actor, "scopes", ()) or ())
        if not _scope_satisfied(t.required_scope, scopes):
            return _denied_result(
                tool_call_id, name,
                f"missing scope: requires {t.required_scope}",
            )

    # ── 3. Validate args ──────────────────────────────────────────
    try:
        args = t.input_schema(**raw_args)
    except ValidationError as exc:
        # Compact, LLM-readable validation message (no full pydantic dump).
        # When a top-level field is missing / invalid, append the field's
        # own ``description`` so the agent's retry has a concrete hint —
        # raw "Field required" alone wasn't enough to teach delete_*
        # callers to pass `reason` (trace d885971d showed 6 retries).
        parts: list[str] = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e["loc"])
            msg = e["msg"]
            hint: str | None = None
            if len(e["loc"]) == 1:
                field_name = str(e["loc"][0])
                field = t.input_schema.model_fields.get(field_name)
                if field is not None and field.description:
                    hint = field.description
            parts.append(f"{loc}: {msg}{f' — {hint}' if hint else ''}")
        return _err_result(
            tool_call_id, name,
            f"validation error: {'; '.join(parts)}",
        )

    # ── 5. Mode guard (do this BEFORE ACL so read_only is fast-fail) ──
    if ctx.agent_runtime_mode == "read_only" and t.mutating:
        return _denied_result(
            tool_call_id, name,
            "read-only mode: mutating tools are disabled",
        )

    # ── 4. ACL check ──────────────────────────────────────────────
    try:
        acl_ok = await _check_acl(t, args, ctx)
    except ToolDenied as exc:
        return _denied_result(tool_call_id, name, str(exc))
    except PermissionError as exc:
        return _denied_result(tool_call_id, name, str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("ACL check raised for tool=%s", name)
        return _err_result(tool_call_id, name, f"ACL check failed: {exc}")
    if not acl_ok:
        return _denied_result(
            tool_call_id, name,
            f"actor lacks {t.required_permission} on {t.permission_target}",
        )

    # ── 6. Drafts routing ────────────────────────────────────────
    draft_redirect: UUID | None = None
    # Swap diagram_id only if the schema has it (view-layer tools).
    if (
        t.mutating
        and ctx.active_draft_id is not None
        and hasattr(args, "diagram_id")
        and getattr(args, "diagram_id", None) is not None
    ):
        try:
            args.diagram_id = ctx.active_draft_id  # type: ignore[attr-defined]
            draft_redirect = ctx.active_draft_id
        except Exception:  # pragma: no cover — Pydantic frozen edge case
            logger.warning("could not redirect diagram_id to draft for tool=%s", name)

    # ── 7-8. Confirmed gate + handler call ───────────────────────
    # Confirmed gate is enforced inside the handler (it inspects args.confirmed).
    # The wrapper just forwards. If the handler returns awaiting_confirmation,
    # we surface that status on ToolExecutionResult.
    try:
        result_dict = await t.handler(args, ctx)
    except ToolDenied as exc:
        return _denied_result(tool_call_id, name, str(exc))
    except AgentError as exc:
        logger.warning("agent error in tool=%s: %s", name, exc)
        await _safe_rollback(ctx)
        return _err_result(tool_call_id, name, str(exc))
    except Exception as exc:
        # Log full traceback locally, return only the message to the LLM.
        logger.error("tool %s raised: %s\n%s", name, exc, traceback.format_exc())
        # Without rollback, asyncpg leaves the transaction in 'aborted'
        # state and every subsequent query in this runtime fails with
        # InFailedSQLTransactionError — including the runtime's own
        # session.flush at the end, which silently drops the assistant
        # message. Always rollback on tool error.
        await _safe_rollback(ctx)
        return _err_result(tool_call_id, name, f"tool execution failed: {exc}")

    if not isinstance(result_dict, dict):
        logger.error("tool %s returned non-dict: %r", name, type(result_dict))
        return _err_result(tool_call_id, name, "tool returned non-dict result")

    # ── 7b. Detect awaiting_confirmation envelope ────────────────
    handler_status = result_dict.get("status")
    if handler_status == "awaiting_confirmation":
        projected = scrub_for_telemetry(result_dict)
        preview = result_dict.get("preview") or "Awaiting confirmation"
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            name=name,
            status="awaiting_confirmation",
            content=json.dumps(projected, default=str),
            preview=str(preview),
            raw=dict(result_dict),
            structured=_structured_record(result_dict, draft_redirect),
        )

    # ── 9. Project output (redaction for LLM boundary) ───────────
    projected = scrub_for_telemetry(result_dict)
    truncated = _truncate_arrays(projected)

    # ── 10. Audit log (mutating only) ────────────────────────────
    if t.mutating:
        try:
            await _write_audit(t, result_dict, ctx)
        except Exception:
            # Audit failure must not propagate into tool failure.
            logger.exception("audit log failed for tool=%s", name)

    # ── 11. Build result ─────────────────────────────────────────
    preview = (
        result_dict.get("preview")
        or _default_preview(t, result_dict)
    )

    structured = _structured_record(result_dict, draft_redirect)

    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        name=name,
        status="ok",
        content=json.dumps(truncated, default=str),
        preview=str(preview),
        raw=dict(result_dict),
        structured=structured,
    )


# ---------------------------------------------------------------------------
# Helpers handlers will use
# ---------------------------------------------------------------------------


def applied_change_record(
    action: str,
    target_type: str,
    target_id: UUID,
    name: str = "",
    **extras: Any,
) -> dict:
    """Build the structured record for ``state.applied_changes`` accumulation.

    Shape mirrors :class:`app.agents.state.ChangeRecord` keys plus a ``metadata``
    bag for tool-specific extras.
    """
    record: dict[str, Any] = {
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
    }
    if name:
        record["name"] = name
    if extras:
        record["metadata"] = extras
    return record


def short_preview(verb: str, target_type: str, name: str) -> str:
    """E.g. ``short_preview('Created', 'object', 'Order Service')`` →
    ``'Created object Order Service'`` (no emoji — UI layer adds icons)."""
    label = f"{verb} {target_type}"
    if name:
        label = f"{label} {name}"
    return label


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scope_satisfied(required_scope: str, actor_scopes: tuple[str, ...]) -> bool:
    required_level = _SCOPE_HIERARCHY.get(required_scope, 0)
    for scope in actor_scopes:
        level = _SCOPE_HIERARCHY.get(scope, -1)
        if level >= required_level:
            return True
    return False


def _err_result(tool_call_id: str, name: str, message: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        name=name,
        status="error",
        content=message,
        preview=f"error: {message[:120]}",
        raw={"error": message},
        structured={},
    )


async def _safe_rollback(ctx: ToolContext) -> None:
    """Roll back the SQLAlchemy session after a tool failure.

    Mandatory after any tool exception that hit the DB — without it, asyncpg
    leaves the underlying transaction in an aborted state and every
    subsequent query in this session (other tools, runtime's own flush,
    even the agent_chat_message INSERT) fails with
    ``InFailedSQLTransactionError``. Logs but does not re-raise — rollback
    is best-effort cleanup.
    """
    db = getattr(ctx, "db", None)
    if db is None:
        return
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001 — never let rollback mask the real error
        logger.debug("safe rollback failed", exc_info=True)


def _denied_result(tool_call_id: str, name: str, message: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_call_id=tool_call_id,
        name=name,
        status="denied",
        content=message,
        preview=f"denied: {message[:120]}",
        raw={"error": message, "code": "denied"},
        structured={},
    )


async def _check_acl(t: Tool, args: BaseModel, ctx: ToolContext) -> bool:
    """Resolve target id from ``permission_target`` and call the appropriate
    :mod:`app.services.access_service` predicate.

    Returns ``True`` when the actor is allowed or the tool requires no permission.
    Returns ``False`` when denied. Raises :class:`ToolDenied` for explicit denials
    that should produce a tailored message; raises :class:`PermissionError` from
    the access layer to be coerced into a denied response by the caller.
    """
    perm = t.required_permission
    if not perm:
        return True

    # Imports kept lazy so test code can monkeypatch the module references
    # without forcing real DB sessions.
    from app.services import access_service, diagram_service, object_service

    # Workspace-scoped tools: the caller already proved workspace membership at
    # auth time; the access_service has per-diagram grants but no workspace-level
    # predicate. We approve here — workspace membership has been validated by
    # the agent runtime entry point. Per-user roles are honoured via
    # access_service for any diagram-scoped action.
    target = t.permission_target
    if target in ("workspace", "none"):
        return True

    # Resolve diagram for ACL.
    diagram = None
    if target == "diagram":
        diagram_id: UUID | None = getattr(args, "diagram_id", None)
        if diagram_id is None:
            raise ToolDenied(
                f"tool {t.name} declares permission_target='diagram' but args has no diagram_id"
            )
        diagram = await diagram_service.get_diagram(ctx.db, diagram_id)
        if diagram is None:
            raise ToolDenied(f"diagram {diagram_id} not found")
    elif target == "object":
        object_id: UUID | None = getattr(args, "object_id", None)
        if object_id is None:
            raise ToolDenied(
                f"tool {t.name} declares permission_target='object' but args has no object_id"
            )
        obj = await object_service.get_object(ctx.db, object_id)
        if obj is None:
            raise ToolDenied(f"object {object_id} not found")
        # Resolve a parent diagram for ACL via diagram_service if available.
        # Phase 1: per-diagram positions decide visibility; lacking that, fall
        # back to workspace-level approval (the actor has already proven workspace
        # membership at runtime entry).
        return True
    elif target == "connection":
        # Same fallback as 'object' — connections are workspace-scoped in Phase 1.
        return True
    else:
        raise ToolDenied(f"unknown permission_target {target!r} for tool {t.name}")

    # We have a Diagram; pick read vs write predicate.
    actor = ctx.actor
    actor_id = getattr(actor, "id", None)
    if actor_id is None:
        raise ToolDenied("actor has no id")

    # Resolve role from workspace membership. For Phase 1 we approve at the
    # workspace level (admins+ always pass); fine-grained role lookup will be
    # wired when access_service exposes a role-fetch helper. We pass Role.EDITOR
    # as a conservative default that lets the access_service evaluate grants.
    from app.models.workspace import Role

    role = getattr(actor, "role", None) or Role.EDITOR

    if perm in ("diagram:read", "workspace:read"):
        return await access_service.can_read_diagram(ctx.db, actor_id, diagram, role)
    # diagram:edit / diagram:manage / workspace:edit → write predicate.
    return await access_service.can_write_diagram(ctx.db, actor_id, diagram, role)


def _truncate_arrays(payload: Any, *, limit: int = 50) -> Any:
    """Truncate any list with > ``limit`` entries, leaving a marker dict.

    Recurses into dicts and lists. Spec §4.8: arrays > 50 truncated with a
    ``_truncated: N more`` marker.
    """
    if isinstance(payload, dict):
        return {k: _truncate_arrays(v, limit=limit) for k, v in payload.items()}
    if isinstance(payload, list):
        if len(payload) > limit:
            kept = [_truncate_arrays(item, limit=limit) for item in payload[:limit]]
            kept.append({"_truncated": len(payload) - limit})
            return kept
        return [_truncate_arrays(item, limit=limit) for item in payload]
    return payload


async def _write_audit(t: Tool, result_dict: dict, ctx: ToolContext) -> None:
    """Append an :class:`ActivityLog` row for a successful mutating tool call.

    We deliberately do not call the ``log_created/updated/deleted`` helpers —
    those expect ORM rows. The handler has already recorded its own
    activity-log entry for the model-level change. Here we add the *agent*
    layer: source/session/tool name metadata.
    """
    from app.models.activity_log import ActivityAction, ActivityLog, ActivityTargetType
    from app.services import activity_service  # noqa: F401  — accessible for tests to patch

    # Map action string ('object.created') to ActivityAction enum.
    action_str = (result_dict.get("action") or "").lower()
    target_type_str = (result_dict.get("target_type") or "").lower()
    target_id = result_dict.get("target_id")

    if not action_str or not target_id:
        # Tool didn't report a structured change — skip silently.
        return

    # Normalize "object.created" → ("object", "created"). Some handlers may
    # emit just "created" — we then fall back to target_type from the result.
    parts = action_str.split(".")
    if len(parts) == 2:
        if not target_type_str:
            target_type_str = parts[0]
        action_kind = parts[1]
    else:
        action_kind = parts[-1]

    try:
        action = ActivityAction(action_kind)
    except ValueError:
        # Not one of created/updated/deleted (e.g. "agent.web_fetch"). Skip
        # the activity_log row but keep telemetry-side tracing in tact.
        logger.debug("skip audit for non-CRUD action %s tool=%s", action_str, t.name)
        return

    try:
        target_type = ActivityTargetType(target_type_str)
    except ValueError:
        logger.debug("skip audit for unknown target_type %s tool=%s", target_type_str, t.name)
        return

    actor = ctx.actor
    user_id = getattr(actor, "id", None) if getattr(actor, "kind", None) == "user" else None

    entry = ActivityLog(
        target_type=target_type,
        target_id=target_id if isinstance(target_id, UUID) else UUID(str(target_id)),
        action=action,
        changes={
            "source": f"agent:{ctx.agent_id}",
            "agent_session_id": str(ctx.session_id),
            "tool_name": t.name,
            "agent_step": result_dict.get("agent_step"),
        },
        user_id=user_id,
        workspace_id=ctx.workspace_id,
    )
    ctx.db.add(entry)
    # Flush is best-effort; the surrounding transaction commits.
    try:
        await ctx.db.flush()
    except Exception:  # pragma: no cover — defensive
        logger.exception("flush failed for agent audit row")


def _structured_record(result_dict: dict, draft_redirect: UUID | None) -> dict:
    """Pull ``action/target_type/target_id/name`` out of a handler result, and
    annotate with ``draft_redirect`` if applicable. Used by the runtime to
    populate ``state.applied_changes``.
    """
    out: dict[str, Any] = {}
    for key in ("action", "target_type", "target_id", "name", "diagram_id"):
        if key in result_dict:
            out[key] = result_dict[key]
    if draft_redirect is not None:
        out["draft_redirect"] = draft_redirect
    return out


def _default_preview(t: Tool, result_dict: dict) -> str:
    """Build a short preview string when the handler didn't set one."""
    if not t.mutating:
        return f"{t.name} ok"
    action = (result_dict.get("action") or "").split(".")
    target_type = result_dict.get("target_type") or ""
    name = result_dict.get("name") or ""
    verb_map = {"created": "Created", "updated": "Updated", "deleted": "Deleted"}
    verb = verb_map.get(action[-1] if action else "", t.name)
    return short_preview(verb, target_type, name)
