"""Tests for app/agents/tools/base.py — Tool / ToolContext / execute_tool wrapper.

Stub handlers + a fake AsyncSession + monkeypatched access_service let us cover
the wrapper without touching real DB or LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.agents.tools.base import (
    Tool,
    ToolContext,
    all_tools,
    applied_change_record,
    clear_tools,
    execute_tool,
    filter_tools,
    get_tool,
    register_tool,
    short_preview,
    tool,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    workspace_id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeSession:
    """In-memory AsyncSession stand-in.

    Only ``add`` + ``flush`` are exercised by the wrapper. ACL checks are
    monkeypatched on the access_service module so we don't need ``execute``.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_calls = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_tools()
    yield
    clear_tools()


def _make_ctx(
    *,
    db: FakeSession | None = None,
    actor: FakeActor | None = None,
    workspace_id: UUID | None = None,
    mode: str = "full",
    active_draft_id: UUID | None = None,
) -> ToolContext:
    ws = workspace_id or uuid4()
    actor_obj = actor or FakeActor(
        kind="user", id=uuid4(), workspace_id=ws, scopes=(), role=None
    )
    return ToolContext(
        db=db or FakeSession(),
        actor=actor_obj,
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode=mode,  # type: ignore[arg-type]
        active_draft_id=active_draft_id,
        draft_target_diagram_id=None,
    )


# ---------------------------------------------------------------------------
# Stub schemas + handlers
# ---------------------------------------------------------------------------


class EchoInput(BaseModel):
    msg: str = "hi"


class DiagramInput(BaseModel):
    diagram_id: UUID
    note: str = ""


class DeleteInput(BaseModel):
    diagram_id: UUID
    confirmed: bool = False


async def _ok_handler(args: BaseModel, ctx: ToolContext) -> dict:
    return {
        "action": "object.created",
        "target_type": "object",
        "target_id": uuid4(),
        "name": "Order Service",
        "preview": "Created object Order Service",
        "api_key": "sk-secretsecret",  # should be redacted in `content`
    }


async def _read_ok_handler(args: BaseModel, ctx: ToolContext) -> dict:
    return {"items": [{"id": str(uuid4()), "name": "X"}]}


async def _diagram_ok_handler(args: DiagramInput, ctx: ToolContext) -> dict:
    return {
        "action": "object.updated",
        "target_type": "object",
        "target_id": uuid4(),
        "diagram_id": args.diagram_id,  # echo what we got
    }


async def _confirmed_gate_handler(args: DeleteInput, ctx: ToolContext) -> dict:
    if not args.confirmed:
        return {
            "status": "awaiting_confirmation",
            "preview": "Will delete diagram X (3 placements, 2 connections)",
            "impact": {"placements": 3, "connections": 2},
        }
    return {
        "action": "diagram.deleted",
        "target_type": "diagram",
        "target_id": args.diagram_id,
    }


async def _raises_handler(args: BaseModel, ctx: ToolContext) -> dict:
    raise RuntimeError("boom: secret-detail-here")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_register_tool_and_get_tool_round_trip():
    t = Tool(
        name="echo",
        description="Echo a message",
        input_schema=EchoInput,
        handler=_read_ok_handler,
        required_permission="",
        permission_target="none",
        required_scope="agents:read",
        mutating=False,
    )
    register_tool(t)
    assert get_tool("echo") is t
    assert all_tools() == [t]


def test_get_tool_missing_raises_keyerror():
    with pytest.raises(KeyError) as exc:
        get_tool("nope")
    assert "nope" in str(exc.value)


def test_register_tool_idempotent_overwrite():
    t1 = Tool(
        name="dup", description="d1", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
    )
    t2 = Tool(
        name="dup", description="d2", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
    )
    register_tool(t1)
    register_tool(t2)
    assert get_tool("dup") is t2


# ---------------------------------------------------------------------------
# OpenAI schema export
# ---------------------------------------------------------------------------


def test_to_openai_schema_shape():
    t = Tool(
        name="echo", description="Echo a message", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
    )
    schema = t.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["description"] == "Echo a message"
    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    assert "msg" in params["properties"]
    # Pydantic title/$defs cleaned up
    assert "title" not in params


# ---------------------------------------------------------------------------
# filter_tools
# ---------------------------------------------------------------------------


def test_filter_tools_scope_drops_higher_scope_tools():
    register_tool(Tool(
        name="read_x", description="r", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
    ))
    register_tool(Tool(
        name="invoke_y", description="i", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:invoke",
    ))
    register_tool(Tool(
        name="write_z", description="w", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:write",
        mutating=True,
    ))

    visible = {t.name for t in filter_tools(scope="agents:read", mode="full")}
    assert visible == {"read_x"}

    visible_invoke = {t.name for t in filter_tools(scope="agents:invoke", mode="full")}
    assert visible_invoke == {"read_x", "invoke_y"}

    visible_write = {t.name for t in filter_tools(scope="agents:write", mode="full")}
    assert visible_write == {"read_x", "invoke_y", "write_z"}


def test_filter_tools_read_only_mode_drops_mutating():
    register_tool(Tool(
        name="read_a", description="r", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
        mutating=False,
    ))
    register_tool(Tool(
        name="write_a", description="w", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:write",
        mutating=True,
    ))
    visible = {t.name for t in filter_tools(scope="agents:admin", mode="read_only")}
    assert visible == {"read_a"}


# ---------------------------------------------------------------------------
# execute_tool — happy / error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_unknown_name():
    ctx = _make_ctx()
    out = await execute_tool({"id": "c1", "name": "ghost", "arguments": {}}, ctx)
    assert out.status == "error"
    assert "not registered" in out.content
    assert out.tool_call_id == "c1"


@pytest.mark.asyncio
async def test_execute_tool_invalid_json_arguments():
    register_tool(Tool(
        name="echo", description="e", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:read",
    ))
    ctx = _make_ctx()
    out = await execute_tool({"id": "c2", "name": "echo", "arguments": "{bad json"}, ctx)
    assert out.status == "error"
    assert "invalid arguments JSON" in out.content


@pytest.mark.asyncio
async def test_execute_tool_validation_error():
    class NeedsField(BaseModel):
        required_field: str

    async def h(args: BaseModel, ctx: ToolContext) -> dict:
        return {}

    register_tool(Tool(
        name="needs_field", description="n", input_schema=NeedsField,
        handler=h, required_permission="",
        permission_target="none", required_scope="agents:read",
    ))
    ctx = _make_ctx()
    out = await execute_tool({"id": "c3", "name": "needs_field", "arguments": {}}, ctx)
    assert out.status == "error"
    assert "validation error" in out.content
    assert "required_field" in out.content


@pytest.mark.asyncio
async def test_execute_tool_acl_deny(monkeypatch):
    register_tool(Tool(
        name="diag_read", description="d", input_schema=DiagramInput,
        handler=_diagram_ok_handler, required_permission="diagram:read",
        permission_target="diagram", required_scope="agents:read",
    ))

    # Fake services: get_diagram returns object; can_read returns False.
    fake_diagram = MagicMock()
    fake_diagram.id = uuid4()

    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=fake_diagram),
    )
    monkeypatch.setattr(
        "app.services.access_service.can_read_diagram",
        AsyncMock(return_value=False),
    )

    ctx = _make_ctx()
    out = await execute_tool(
        {"id": "c4", "name": "diag_read", "arguments": {"diagram_id": str(uuid4())}},
        ctx,
    )
    assert out.status == "denied"
    assert "diagram:read" in out.content


@pytest.mark.asyncio
async def test_execute_tool_read_only_blocks_mutating():
    register_tool(Tool(
        name="mutate_x", description="m", input_schema=EchoInput,
        handler=_ok_handler, required_permission="",
        permission_target="none", required_scope="agents:write",
        mutating=True,
    ))
    ctx = _make_ctx(mode="read_only")
    out = await execute_tool({"id": "c5", "name": "mutate_x", "arguments": {}}, ctx)
    assert out.status == "denied"
    assert "read-only mode" in out.content


# ---------------------------------------------------------------------------
# execute_tool — drafts routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_drafts_routing(monkeypatch):
    register_tool(Tool(
        name="diag_edit", description="d", input_schema=DiagramInput,
        handler=_diagram_ok_handler, required_permission="diagram:edit",
        permission_target="diagram", required_scope="agents:write",
        mutating=True,
    ))

    fake_diagram = MagicMock()
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=fake_diagram),
    )
    monkeypatch.setattr(
        "app.services.access_service.can_write_diagram",
        AsyncMock(return_value=True),
    )

    draft_id = uuid4()
    base_diagram_id = uuid4()
    ctx = _make_ctx(active_draft_id=draft_id)
    out = await execute_tool(
        {
            "id": "c6", "name": "diag_edit",
            "arguments": {"diagram_id": str(base_diagram_id)},
        },
        ctx,
    )
    assert out.status == "ok"
    # Handler echoed back the diagram_id — should now be the draft.
    assert str(draft_id) in out.content
    assert out.structured.get("draft_redirect") == draft_id


# ---------------------------------------------------------------------------
# execute_tool — confirmed gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_confirmed_gate_passthrough(monkeypatch):
    register_tool(Tool(
        name="delete_diag", description="d", input_schema=DeleteInput,
        handler=_confirmed_gate_handler, required_permission="diagram:manage",
        permission_target="diagram", required_scope="agents:admin",
        mutating=True, deprecates_model=True, needs_confirmed_gate=True,
    ))

    fake_diagram = MagicMock()
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=fake_diagram),
    )
    monkeypatch.setattr(
        "app.services.access_service.can_write_diagram",
        AsyncMock(return_value=True),
    )

    ctx = _make_ctx()
    out = await execute_tool(
        {
            "id": "c7", "name": "delete_diag",
            "arguments": {"diagram_id": str(uuid4()), "confirmed": False},
        },
        ctx,
    )
    assert out.status == "awaiting_confirmation"
    assert "Will delete" in out.preview


# ---------------------------------------------------------------------------
# execute_tool — happy path with audit + redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_happy_path_audits_and_redacts(monkeypatch):
    register_tool(Tool(
        name="create_thing", description="c", input_schema=EchoInput,
        handler=_ok_handler, required_permission="",
        permission_target="workspace", required_scope="agents:write",
        mutating=True,
    ))

    db = FakeSession()
    ctx = _make_ctx(db=db)

    out = await execute_tool(
        {"id": "c8", "name": "create_thing", "arguments": {"msg": "hi"}},
        ctx,
    )
    assert out.status == "ok"
    # api_key value redacted in projected content
    assert "sk-secretsecret" not in out.content
    assert "<redacted: api_key>" in out.content
    # raw retains the unredacted dict for storage in agent_chat_message
    assert out.raw["api_key"] == "sk-secretsecret"
    # Audit row added (one ActivityLog row in db.added)
    assert len(db.added) == 1
    audit = db.added[0]
    changes = getattr(audit, "changes", {}) or {}
    assert changes.get("source") == "agent:general"
    assert changes.get("tool_name") == "create_thing"
    # structured fields populated for applied_changes accumulation
    assert out.structured.get("action") == "object.created"
    assert out.structured.get("target_type") == "object"


@pytest.mark.asyncio
async def test_execute_tool_read_only_tool_skips_audit(monkeypatch):
    register_tool(Tool(
        name="read_thing", description="r", input_schema=EchoInput,
        handler=_read_ok_handler, required_permission="",
        permission_target="workspace", required_scope="agents:read",
        mutating=False,
    ))
    db = FakeSession()
    ctx = _make_ctx(db=db)
    out = await execute_tool(
        {"id": "c9", "name": "read_thing", "arguments": {}},
        ctx,
    )
    assert out.status == "ok"
    assert db.added == []  # no audit row for read tools


# ---------------------------------------------------------------------------
# execute_tool — exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_handler_exception(caplog):
    register_tool(Tool(
        name="bomb", description="b", input_schema=EchoInput,
        handler=_raises_handler, required_permission="",
        permission_target="none", required_scope="agents:invoke",
    ))
    ctx = _make_ctx()
    with caplog.at_level("ERROR"):
        out = await execute_tool({"id": "c10", "name": "bomb", "arguments": {}}, ctx)
    assert out.status == "error"
    # Message surfaced to LLM, but stack trace only in logs.
    assert "boom" in out.content
    assert "Traceback" not in out.content
    # The full traceback was logged.
    assert any("Traceback" in r.message for r in caplog.records if r.message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_applied_change_record_basic():
    tid = uuid4()
    rec = applied_change_record("object.created", "object", tid, name="X")
    assert rec == {
        "action": "object.created",
        "target_type": "object",
        "target_id": tid,
        "name": "X",
    }


def test_applied_change_record_with_extras():
    tid = uuid4()
    rec = applied_change_record("object.updated", "object", tid, diagram_id="abc")
    assert rec["metadata"] == {"diagram_id": "abc"}


def test_short_preview_basic():
    assert short_preview("Created", "object", "Order Service") == "Created object Order Service"
    assert short_preview("Deleted", "diagram", "") == "Deleted diagram"


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def test_tool_decorator_registers():
    @tool(
        name="dec_demo",
        description="demo",
        input_schema=EchoInput,
        permission="",
        permission_target="none",
        required_scope="agents:read",
    )
    async def _demo(args, ctx):
        return {}

    assert isinstance(_demo, Tool)
    assert get_tool("dec_demo") is _demo
