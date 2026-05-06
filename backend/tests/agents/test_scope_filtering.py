"""Tests for API-key scope filtering (task agent-core-mvp-039).

Covers:
  - _has_scope hierarchy logic
  - filter_tools_for_actor (api_key + user + mode)
  - _make_tool_executor: api_key with insufficient scope → denied
  - ALLOWED_SCOPES validation in ApiKeyCreate
  - Integration smoke: read-tool allowed, write-tool denied for agents:read key
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.runtime import (
    ActorRef,
    ChatContext,
    _has_scope,
    _make_tool_executor,
    filter_tools_for_actor,
)
from app.agents.tools.base import Tool, clear_tools, register_tool
from app.schemas.api_key import ApiKeyCreate

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _EmptyInput(BaseModel):
    pass


async def _noop_handler(args: BaseModel, ctx: Any) -> dict:
    return {"status": "ok"}


def _make_actor(
    kind: str = "api_key",
    scopes: tuple[str, ...] = (),
) -> ActorRef:
    return ActorRef(
        kind=kind,  # type: ignore[arg-type]
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=scopes,
        agent_access="full" if kind == "user" else None,
    )


def _tool_schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


@pytest.fixture(autouse=True)
def clean_tool_registry():
    """Isolate the tool registry for every test."""
    clear_tools()
    yield
    clear_tools()


def _register(name: str, *, required_scope: str = "agents:invoke", mutating: bool = False) -> Tool:
    t = Tool(
        name=name,
        description=f"Test tool {name}",
        input_schema=_EmptyInput,
        handler=_noop_handler,
        required_scope=required_scope,
        mutating=mutating,
    )
    register_tool(t)
    return t


# ---------------------------------------------------------------------------
# _has_scope tests
# ---------------------------------------------------------------------------


def test_has_scope_exact_read_satisfied():
    """agents:read tool, actor has agents:read → True."""
    assert _has_scope(("agents:read",), "agents:read") is True


def test_has_scope_write_with_read_denied():
    """agents:write tool, actor has agents:read → False."""
    assert _has_scope(("agents:read",), "agents:write") is False


def test_has_scope_write_with_admin_satisfied():
    """agents:write tool, actor has agents:admin → True (admin > write)."""
    assert _has_scope(("agents:admin",), "agents:write") is True


def test_has_scope_invoke_with_admin():
    """agents:invoke tool, actor has agents:admin → True."""
    assert _has_scope(("agents:admin",), "agents:invoke") is True


def test_has_scope_wildcard_always_true():
    """Wildcard '*' satisfies any scope."""
    assert _has_scope(("*",), "agents:admin") is True
    assert _has_scope(("*",), "agents:write") is True
    assert _has_scope({"*"}, "agents:read") is True


def test_has_scope_empty_actor_denied():
    """Empty scopes → denied for anything."""
    assert _has_scope((), "agents:read") is False
    assert _has_scope((), "agents:invoke") is False


# ---------------------------------------------------------------------------
# filter_tools_for_actor tests
# ---------------------------------------------------------------------------


def test_filter_tools_api_key_read_scope_drops_write_tool():
    """ApiKey scopes=['agents:read'] + mutating write-scoped tool → dropped."""
    _register("read_object", required_scope="agents:read", mutating=False)
    _register("create_object", required_scope="agents:write", mutating=True)

    actor = _make_actor(kind="api_key", scopes=("agents:read",))
    schemas = [_tool_schema("read_object"), _tool_schema("create_object")]

    result = filter_tools_for_actor(schemas, actor=actor, mode="full")
    names = [s["function"]["name"] for s in result]
    assert "read_object" in names
    assert "create_object" not in names


def test_filter_tools_user_actor_no_scope_filter():
    """User actor → no scope filter applied; only mode filter active."""
    _register("read_object", required_scope="agents:read", mutating=False)
    _register("create_object", required_scope="agents:write", mutating=True)

    actor = _make_actor(kind="user")
    schemas = [_tool_schema("read_object"), _tool_schema("create_object")]

    # full mode: user sees everything
    result = filter_tools_for_actor(schemas, actor=actor, mode="full")
    names = [s["function"]["name"] for s in result]
    assert "read_object" in names
    assert "create_object" in names


def test_filter_tools_read_only_mode_drops_mutating():
    """mode=read_only + mutating tool → dropped regardless of actor scopes."""
    _register("read_object", required_scope="agents:read", mutating=False)
    _register("create_object", required_scope="agents:invoke", mutating=True)

    # Even an admin key can't use mutating tools in read_only mode.
    actor = _make_actor(kind="api_key", scopes=("agents:admin",))
    schemas = [_tool_schema("read_object"), _tool_schema("create_object")]

    result = filter_tools_for_actor(schemas, actor=actor, mode="read_only")
    names = [s["function"]["name"] for s in result]
    assert "read_object" in names
    assert "create_object" not in names


def test_filter_tools_user_read_only_drops_mutating():
    """User actor in read_only mode → mutating tool dropped."""
    _register("read_object", required_scope="agents:read", mutating=False)
    _register("delete_object", required_scope="agents:write", mutating=True)

    actor = _make_actor(kind="user")
    schemas = [_tool_schema("read_object"), _tool_schema("delete_object")]

    result = filter_tools_for_actor(schemas, actor=actor, mode="read_only")
    names = [s["function"]["name"] for s in result]
    assert "read_object" in names
    assert "delete_object" not in names


def test_filter_tools_unregistered_tool_passes_through():
    """Schemas for tools not in the registry pass through unchanged."""
    # Don't register anything — simulate a plumbing tool not in the registry.
    actor = _make_actor(kind="api_key", scopes=("agents:read",))
    schema = _tool_schema("write_scratchpad")

    result = filter_tools_for_actor([schema], actor=actor, mode="full")
    assert len(result) == 1
    assert result[0]["function"]["name"] == "write_scratchpad"


# ---------------------------------------------------------------------------
# _make_tool_executor — scope denial test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_tool_executor_api_key_insufficient_scope_returns_denied():
    """ApiKey actor with agents:read scope can't invoke an agents:write tool."""
    _register("create_object", required_scope="agents:write", mutating=True)

    actor = _make_actor(kind="api_key", scopes=("agents:read",))
    fake_db = MagicMock()
    ctx = ChatContext(kind="none")

    executor = _make_tool_executor(
        db=fake_db,
        actor=actor,
        workspace_id=uuid4(),
        chat_context=ctx,
        active_draft_id=None,
        agent_id="test-agent",
        mode="full",
    )

    result = await executor(
        {"id": "call-1", "name": "create_object", "arguments": {}},
        {"session_id": uuid4()},
    )

    assert result["status"] == "denied"
    assert "agents:write" in result["content"]


@pytest.mark.asyncio
async def test_make_tool_executor_api_key_unknown_tool_returns_error():
    """Calling an unregistered tool via api_key path returns status='error'."""
    actor = _make_actor(kind="api_key", scopes=("agents:admin",))
    fake_db = MagicMock()
    ctx = ChatContext(kind="none")

    executor = _make_tool_executor(
        db=fake_db,
        actor=actor,
        workspace_id=uuid4(),
        chat_context=ctx,
        active_draft_id=None,
        agent_id="test-agent",
        mode="full",
    )

    result = await executor(
        {"id": "call-2", "name": "nonexistent_tool", "arguments": {}},
        {"session_id": uuid4()},
    )

    assert result["status"] == "error"
    assert "nonexistent_tool" in result["content"]


# ---------------------------------------------------------------------------
# ALLOWED_SCOPES validation in ApiKeyCreate
# ---------------------------------------------------------------------------


def test_api_key_create_rejects_unknown_scope():
    """Unknown scope string → ValueError from the validator."""
    with pytest.raises(ValidationError) as exc_info:
        ApiKeyCreate(name="my-key", permissions=["agents:unknown"])
    assert "unknown scopes" in str(exc_info.value).lower()


def test_api_key_create_accepts_known_agent_scopes():
    """All new agent scopes are accepted without error."""
    for scope in ("agents:read", "agents:invoke", "agents:write", "agents:admin"):
        key = ApiKeyCreate(name="my-key", permissions=[scope])
        assert scope in key.permissions


def test_api_key_create_accepts_legacy_scopes():
    """Legacy 'read', 'write', 'admin' tokens remain valid."""
    for scope in ("read", "write", "admin"):
        key = ApiKeyCreate(name="my-key", permissions=[scope])
        assert scope in key.permissions


def test_api_key_create_accepts_wildcard():
    """Wildcard '*' is in ALLOWED_SCOPES."""
    key = ApiKeyCreate(name="my-key", permissions=["*"])
    assert "*" in key.permissions


# ---------------------------------------------------------------------------
# Integration smoke: read tool allowed, write tool denied for agents:read key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_read_allowed_write_denied_for_agents_read_key():
    """ApiKey with 'agents:read' scope can call read tools, can't call write tools."""
    _register("read_object", required_scope="agents:read", mutating=False)
    _register("create_object", required_scope="agents:write", mutating=True)

    actor = ActorRef(
        kind="api_key",
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=("agents:read",),
    )
    fake_db = AsyncMock()
    # Patch execute_tool to return a minimal ok result for the read tool.
    from app.agents.tools.base import ToolContext

    async def fake_execute_tool(call: dict, ctx: ToolContext):  # type: ignore[return]
        from app.agents.tools.base import ToolExecutionResult

        return ToolExecutionResult(
            tool_call_id=call.get("id", ""),
            name=call.get("name", ""),
            status="ok",
            content="{}",
            preview="ok",
        )

    original_execute = None
    import app.agents.tools.base as base_mod

    original_execute = base_mod.execute_tool

    try:
        base_mod.execute_tool = fake_execute_tool  # type: ignore[assignment]

        executor = _make_tool_executor(
            db=fake_db,
            actor=actor,
            workspace_id=actor.workspace_id,
            chat_context=ChatContext(kind="none"),
            active_draft_id=None,
            agent_id="smoke-test",
            mode="full",
        )

        # Read tool → should pass scope check (scope check in executor, not execute_tool)
        read_result = await executor(
            {"id": "r1", "name": "read_object", "arguments": {}},
            {"session_id": uuid4()},
        )
        assert read_result["status"] == "ok", f"Expected ok, got: {read_result}"

        # Write tool → denied before reaching execute_tool
        write_result = await executor(
            {"id": "w1", "name": "create_object", "arguments": {}},
            {"session_id": uuid4()},
        )
        assert write_result["status"] == "denied"
        assert "agents:write" in write_result["content"]
    finally:
        base_mod.execute_tool = original_execute  # type: ignore[assignment]
