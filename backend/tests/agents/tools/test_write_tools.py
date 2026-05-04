"""Tests for the write tools in app/agents/tools/{model,view}_tools.py.

Mocks ``object_service``/``connection_service``/``diagram_service`` so tests
exercise the wrapper + handler logic without needing a real DB or layout engine.

Layout engine: ``_resolve_position`` in view_tools normally calls
``app.agents.layout.engine.incremental_place``. That function raises
NotImplementedError until task agent-core-mvp-053 lands; the wrapper falls
back to a 16-aligned grid heuristic (``_grid_fallback``). The test for
``place_on_diagram`` without x/y coordinates exercises that fallback path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import app.agents.tools.model_tools as model_tools  # noqa: F401  — register tools
import app.agents.tools.view_tools as view_tools  # noqa: F401  — register tools
from app.agents.tools.base import (
    ToolContext,
    clear_tools,
    execute_tool,
    get_tool,
    register_tool,
)


def _reregister_all_tools() -> None:
    """Re-register every Tool defined as a module-level constant in model/view tools.

    Decorator-registered tools were registered at import time, but other test
    modules call ``clear_tools()`` between sessions; we re-register on every
    test invocation so this file can run in any order.
    """
    from app.agents.tools.base import Tool as _Tool

    for module in (model_tools, view_tools):
        for attr in vars(module).values():
            if isinstance(attr, _Tool):
                register_tool(attr)


@pytest.fixture(autouse=True)
def _ensure_tools_registered():
    """Mirror test_base.py's clear_tools fixture: clear → re-register all
    write-tool definitions so the registry is in a known state."""
    clear_tools()
    _reregister_all_tools()
    yield
    clear_tools()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID = field(default_factory=uuid4)
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeSession:
    """In-memory AsyncSession stand-in used by base.execute_tool's ACL/audit."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def execute(self, *_args, **_kwargs):  # pragma: no cover — defensive
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result


def _ctx(
    *,
    db: FakeSession | None = None,
    actor: FakeActor | None = None,
    workspace_id: UUID | None = None,
    mode: str = "full",
    active_draft_id: UUID | None = None,
) -> ToolContext:
    ws = workspace_id or uuid4()
    actor_obj = actor or FakeActor(workspace_id=ws)
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


def _patch_acl_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ACL helpers always succeed for tests that exercise tool logic."""
    fake_diagram = MagicMock()
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=fake_diagram),
    )
    monkeypatch.setattr(
        "app.services.access_service.can_read_diagram",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.access_service.can_write_diagram",
        AsyncMock(return_value=True),
    )


def _make_object_row(**overrides: Any) -> Any:
    obj = MagicMock()
    obj.id = overrides.get("id", uuid4())
    obj.name = overrides.get("name", "Order Service")
    obj.type = overrides.get("type", MagicMock(value="app"))
    obj.parent_id = overrides.get("parent_id")
    obj.description = overrides.get("description")
    obj.technology_ids = overrides.get("technology_ids", [])
    obj.tags = overrides.get("tags", [])
    obj.owner_team = overrides.get("owner_team")
    obj.status = overrides.get("status", MagicMock(value="live"))
    obj.scope = overrides.get("scope", MagicMock(value="internal"))
    obj.workspace_id = overrides.get("workspace_id", uuid4())
    obj.c4_level = overrides.get("c4_level", "L2")
    return obj


def _make_connection_row(**overrides: Any) -> Any:
    conn = MagicMock()
    conn.id = overrides.get("id", uuid4())
    conn.source_id = overrides.get("source_id", uuid4())
    conn.target_id = overrides.get("target_id", uuid4())
    conn.label = overrides.get("label", "calls")
    conn.protocol_ids = overrides.get("protocol_ids", [])
    conn.direction = overrides.get("direction", MagicMock(value="unidirectional"))
    return conn


def _make_diagram_row(**overrides: Any) -> Any:
    d = MagicMock()
    d.id = overrides.get("id", uuid4())
    d.name = overrides.get("name", "L2 - Container")
    d.type = overrides.get("type", MagicMock(value="container"))
    d.description = overrides.get("description")
    d.scope_object_id = overrides.get("scope_object_id")
    d.workspace_id = overrides.get("workspace_id", uuid4())
    d.objects = overrides.get("objects", [])
    return d


def _make_placement(**overrides: Any) -> Any:
    p = MagicMock()
    p.object_id = overrides.get("object_id", uuid4())
    p.position_x = overrides.get("position_x", 0.0)
    p.position_y = overrides.get("position_y", 0.0)
    p.width = overrides.get("width", 220)
    p.height = overrides.get("height", 120)
    return p


# ---------------------------------------------------------------------------
# Model write tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_object_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    new_obj = _make_object_row(name="Order Service")
    monkeypatch.setattr(
        "app.services.object_service.create_object",
        AsyncMock(return_value=new_obj),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c1",
            "name": "create_object",
            "arguments": {"name": "Order Service", "type": "app"},
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.created"
    assert out.structured.get("target_type") == "object"
    assert "Order Service" in out.preview


@pytest.mark.asyncio
async def test_create_object_returns_reused_when_duplicate(monkeypatch):
    """Server-side dedup: when ``object_service.create_object`` raises
    ``DuplicateObjectError``, the agent's tool wrapper must surface
    ``action='object.reused'`` with the existing id — never crash the turn,
    never create a duplicate."""
    _patch_acl_pass(monkeypatch)

    existing = _make_object_row(name="Postgres")
    from app.services import object_service

    async def boom(*_a, **_kw):
        raise object_service.DuplicateObjectError(existing)

    monkeypatch.setattr(
        "app.services.object_service.create_object", boom
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "cdup",
            "name": "create_object",
            "arguments": {"name": "Postgres", "type": "store"},
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.reused"
    assert out.structured.get("target_id") == existing.id
    assert out.structured.get("name") == "Postgres"
    # Full payload keeps the explicit reused flag so downstream node parsers
    # can distinguish a fresh creation from a dedup.
    import json as _json

    body = _json.loads(out.content)
    assert body.get("status") == "reused"


@pytest.mark.asyncio
async def test_create_object_publishes_ws_event(monkeypatch):
    """Live-canvas update path: ``create_object`` must publish to the
    workspace WS channel so open canvases refresh without waiting for the
    SSE applied_change → REST refetch round-trip."""
    _patch_acl_pass(monkeypatch)

    new_obj = _make_object_row(name="Order Service")
    monkeypatch.setattr(
        "app.services.object_service.create_object",
        AsyncMock(return_value=new_obj),
    )

    # Stub the response schema so MagicMock fixtures don't fail Pydantic's
    # field validation — we care that publish runs, not what it serialises.
    class _StubResponse:
        def __init__(self, name: str, obj_id: Any) -> None:
            self._body = {"id": str(obj_id), "name": name}

        def model_dump(self, **_kw: Any) -> dict:
            return dict(self._body)

    monkeypatch.setattr(
        "app.schemas.object.ObjectResponse.from_model",
        classmethod(lambda cls, o: _StubResponse(o.name, o.id)),
    )

    captured: list[tuple] = []
    monkeypatch.setattr(
        "app.agents.tools._realtime.fire_and_forget_publish",
        lambda ws_id, event_type, payload: captured.append(
            ("publish", ws_id, event_type, payload)
        ),
    )
    monkeypatch.setattr(
        "app.agents.tools._realtime.fire_and_forget_emit",
        lambda event_type, body: captured.append(("emit", event_type, body)),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c1",
            "name": "create_object",
            "arguments": {"name": "Order Service", "type": "app"},
        },
        ctx,
    )
    assert out.status == "ok", out.content

    publish_calls = [c for c in captured if c[0] == "publish"]
    emit_calls = [c for c in captured if c[0] == "emit"]
    assert len(publish_calls) == 1
    assert publish_calls[0][2] == "object.created"
    assert "object" in publish_calls[0][3]
    assert publish_calls[0][3]["object"]["name"] == "Order Service"
    assert len(emit_calls) == 1
    assert emit_calls[0][1] == "object.created"


@pytest.mark.asyncio
async def test_create_object_validation_missing_name(monkeypatch):
    _patch_acl_pass(monkeypatch)

    ctx = _ctx()
    out = await execute_tool(
        {"id": "c2", "name": "create_object", "arguments": {"type": "app"}},
        ctx,
    )
    assert out.status == "error"
    assert "validation error" in out.content
    assert "name" in out.content


@pytest.mark.asyncio
async def test_update_object_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Old Name")
    updated = _make_object_row(id=obj.id, name="New Name")
    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    monkeypatch.setattr(
        "app.services.object_service.update_object",
        AsyncMock(return_value=updated),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c3",
            "name": "update_object",
            "arguments": {
                "object_id": str(obj.id),
                "patch": {"name": "New Name"},
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.updated"
    assert out.structured.get("target_id") == updated.id


@pytest.mark.asyncio
async def test_delete_object_preview_when_not_confirmed(monkeypatch):
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Doomed")
    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value={
            "upstream": [_make_connection_row(), _make_connection_row()],
            "downstream": [_make_connection_row()],
        }),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        AsyncMock(return_value=[_make_diagram_row(), _make_diagram_row()]),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams",
        AsyncMock(return_value=[_make_diagram_row()]),
    )
    delete_mock = AsyncMock()
    monkeypatch.setattr("app.services.object_service.delete_object", delete_mock)

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c4",
            "name": "delete_object",
            "arguments": {
                "object_id": str(obj.id),
                "confirmed": False,
                "reason": "duplicate object cleanup",
            },
        },
        ctx,
    )
    assert out.status == "awaiting_confirmation"
    assert "Will delete" in out.preview
    impact = out.raw["impact"]
    assert impact["will_delete"] == 1
    assert impact["will_orphan_connections"] == 3
    assert impact["will_orphan_placements"] == 2
    assert len(impact["child_diagrams"]) == 1
    delete_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_object_confirmed_executes(monkeypatch):
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Doomed")
    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.object_service.delete_object", delete_mock
    )

    ctx = _ctx()
    # Without an LLM client wired into ToolContext the destructive-op
    # reviewer auto-approves with a marker rationale (it's a safety net,
    # not a hard gate). Tests rely on that fallback.
    out = await execute_tool(
        {
            "id": "c5",
            "name": "delete_object",
            "arguments": {
                "object_id": str(obj.id),
                "confirmed": True,
                "reason": "duplicate object cleanup",
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.deleted"
    delete_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_connection_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    conn = _make_connection_row(label="api call")
    monkeypatch.setattr(
        "app.services.connection_service.create_connection",
        AsyncMock(return_value=conn),
    )

    src = uuid4()
    tgt = uuid4()
    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c6",
            "name": "create_connection",
            "arguments": {
                "source_object_id": str(src),
                "target_object_id": str(tgt),
                "label": "api call",
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "connection.created"
    assert out.structured.get("target_id") == conn.id


@pytest.mark.asyncio
async def test_create_connection_explicit_handles_win(monkeypatch):
    """Agent-supplied handle values must override the auto-pick path."""
    _patch_acl_pass(monkeypatch)

    create_mock = AsyncMock(return_value=_make_connection_row(label="api call"))
    monkeypatch.setattr(
        "app.services.connection_service.create_connection", create_mock
    )
    # Auto-pick would normally probe shared diagrams; force the geometry
    # path to return a different pair so we can prove the override wins.
    from app.agents.tools import _handle_resolver

    monkeypatch.setattr(
        _handle_resolver,
        "resolve_handles_for_connection",
        AsyncMock(return_value=("right", "left")),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c6h",
            "name": "create_connection",
            "arguments": {
                "source_object_id": str(uuid4()),
                "target_object_id": str(uuid4()),
                "source_handle": "top",
                "target_handle": "bottom",
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    create_data = create_mock.await_args.args[1]
    assert create_data.source_handle == "top"
    assert create_data.target_handle == "bottom"


@pytest.mark.asyncio
async def test_create_connection_auto_handles_when_no_explicit(monkeypatch):
    """Without explicit handles, the resolver's pair gets persisted."""
    _patch_acl_pass(monkeypatch)

    create_mock = AsyncMock(return_value=_make_connection_row(label="api call"))
    monkeypatch.setattr(
        "app.services.connection_service.create_connection", create_mock
    )
    from app.agents.tools import _handle_resolver

    monkeypatch.setattr(
        _handle_resolver,
        "resolve_handles_for_connection",
        AsyncMock(return_value=("right", "left")),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c6a",
            "name": "create_connection",
            "arguments": {
                "source_object_id": str(uuid4()),
                "target_object_id": str(uuid4()),
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    create_data = create_mock.await_args.args[1]
    assert create_data.source_handle == "right"
    assert create_data.target_handle == "left"


@pytest.mark.asyncio
async def test_create_connection_drops_invalid_handle_value(monkeypatch):
    """Agent-supplied junk handle name must be ignored, not propagated."""
    _patch_acl_pass(monkeypatch)

    create_mock = AsyncMock(return_value=_make_connection_row(label="api call"))
    monkeypatch.setattr(
        "app.services.connection_service.create_connection", create_mock
    )
    from app.agents.tools import _handle_resolver

    monkeypatch.setattr(
        _handle_resolver,
        "resolve_handles_for_connection",
        AsyncMock(return_value=(None, None)),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c6j",
            "name": "create_connection",
            "arguments": {
                "source_object_id": str(uuid4()),
                "target_object_id": str(uuid4()),
                "source_handle": "center",  # not in {top,right,bottom,left}
                "target_handle": "diagonal",
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    create_data = create_mock.await_args.args[1]
    # Invalid values dropped → resolver returned None → handles stay None.
    assert create_data.source_handle is None
    assert create_data.target_handle is None


@pytest.mark.asyncio
async def test_delete_connection_preview_then_confirmed(monkeypatch):
    _patch_acl_pass(monkeypatch)

    conn = _make_connection_row(label="some call")
    get_conn = AsyncMock(return_value=conn)
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.connection_service.get_connection", get_conn
    )
    monkeypatch.setattr(
        "app.services.connection_service.delete_connection", delete_mock
    )

    ctx = _ctx()
    # Step 1: preview.
    out1 = await execute_tool(
        {
            "id": "c7",
            "name": "delete_connection",
            "arguments": {
                "connection_id": str(conn.id),
                "confirmed": False,
                "reason": "removing stale link as part of cleanup",
            },
        },
        ctx,
    )
    assert out1.status == "awaiting_confirmation"
    assert out1.raw["impact"]["will_delete"] == 1
    delete_mock.assert_not_called()

    # Step 2: confirmed.
    out2 = await execute_tool(
        {
            "id": "c8",
            "name": "delete_connection",
            "arguments": {
                "connection_id": str(conn.id),
                "confirmed": True,
                "reason": "removing stale link as part of cleanup",
            },
        },
        ctx,
    )
    assert out2.status == "ok", out2.content
    assert out2.structured.get("action") == "connection.deleted"
    delete_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# View tools — placements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_on_diagram_with_xy_uses_provided_coords(monkeypatch):
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Cache")
    placement = _make_placement(
        object_id=obj.id, position_x=100, position_y=200, width=180, height=80
    )

    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    add_mock = AsyncMock(return_value=placement)
    monkeypatch.setattr(
        "app.services.diagram_service.add_object_to_diagram", add_mock
    )

    diagram_id = uuid4()
    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c9",
            "name": "place_on_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "object_id": str(obj.id),
                "x": 100,
                "y": 200,
                "width": 180,
                "height": 80,
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.placed"
    add_mock.assert_awaited_once()
    # Verify the (x, y) actually passed in were honoured (not auto-resolved).
    call_args = add_mock.await_args
    create_data = call_args.args[2]
    assert create_data.position_x == 100
    assert create_data.position_y == 200


@pytest.mark.asyncio
async def test_place_on_diagram_without_xy_uses_grid_fallback(monkeypatch):
    """Layout engine raises NotImplementedError → grid fallback at (64, 64).

    Force the engine to raise so we exercise the fallback path even when the
    real implementation is wired up.
    """
    _patch_acl_pass(monkeypatch)

    async def _engine_raises(**_kwargs):
        raise NotImplementedError("force fallback in test")

    monkeypatch.setattr(
        "app.agents.layout.engine.incremental_place", _engine_raises
    )

    obj = _make_object_row(name="API GW")
    placement = _make_placement(object_id=obj.id, position_x=64, position_y=64)

    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    # Empty diagram → first cell at (64, 64). Two callers in the new
    # place_on_diagram (dedupe pre-check + grid fallback) — return [] for
    # both so we hit the empty-grid path.
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(return_value=[]),
    )
    add_mock = AsyncMock(return_value=placement)
    monkeypatch.setattr(
        "app.services.diagram_service.add_object_to_diagram", add_mock
    )

    diagram_id = uuid4()
    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c10",
            "name": "place_on_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "object_id": str(obj.id),
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    add_mock.assert_awaited_once()
    create_data = add_mock.await_args.args[2]
    # Grid fallback origin is (64, 64) when the diagram is empty.
    assert create_data.position_x == 64
    assert create_data.position_y == 64


@pytest.mark.asyncio
async def test_move_on_diagram_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    moved = _make_placement(position_x=300, position_y=400)
    update_mock = AsyncMock(return_value=moved)
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram_object", update_mock
    )

    diagram_id = uuid4()
    object_id = uuid4()
    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c11",
            "name": "move_on_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "object_id": str(object_id),
                "x": 300,
                "y": 400,
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "object.moved"
    update_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_unplace_from_diagram_preview_with_affected_connections(monkeypatch):
    _patch_acl_pass(monkeypatch)

    object_id = uuid4()
    other_id = uuid4()
    diagram_id = uuid4()

    # Two upstream connections, one with both endpoints placed (counts), one with only one.
    upstream_visible = _make_connection_row(source_id=other_id, target_id=object_id)
    upstream_invisible = _make_connection_row(source_id=uuid4(), target_id=object_id)

    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value={
            "upstream": [upstream_visible, upstream_invisible],
            "downstream": [],
        }),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(return_value=[
            _make_placement(object_id=object_id),
            _make_placement(object_id=other_id),
        ]),
    )
    remove_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.diagram_service.remove_object_from_diagram",
        remove_mock,
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c12",
            "name": "unplace_from_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "object_id": str(object_id),
                "confirmed": False,
                "reason": "moving placement to a different diagram",
            },
        },
        ctx,
    )
    assert out.status == "awaiting_confirmation"
    assert out.raw["impact"]["will_orphan_connections_on_diagram"] == 1
    remove_mock.assert_not_called()


# ---------------------------------------------------------------------------
# View tools — diagram CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_diagram_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    new_diag = _make_diagram_row(name="L2 Container")
    create_mock = AsyncMock(return_value=new_diag)
    monkeypatch.setattr("app.services.diagram_service.create_diagram", create_mock)

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c13",
            "name": "create_diagram",
            "arguments": {"name": "L2 Container", "level": "L2"},
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "diagram.created"
    assert out.structured.get("target_id") == new_diag.id
    create_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_child_diagram_for_object_reuses_existing(monkeypatch):
    """Server-side dedup: a second `create_child_diagram_for_object` call on
    the same object reuses the existing live child diagram instead of
    creating a duplicate (see trace 355785c7 for why)."""
    _patch_acl_pass(monkeypatch)

    obj_id = uuid4()
    parent_obj = _make_object_row(id=obj_id, name="Facade", c4_level="L2")
    parent_obj.type = MagicMock(value="app")
    existing_child = _make_diagram_row(name="Facade Internal")
    existing_child.draft_id = None
    existing_child.scope_object_id = obj_id

    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=parent_obj),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams",
        AsyncMock(return_value=[existing_child]),
    )
    create_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.diagram_service.create_diagram", create_mock
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "ccd1",
            "name": "create_child_diagram_for_object",
            "arguments": {"object_id": str(obj_id)},
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "diagram.reused"
    assert out.structured.get("target_id") == existing_child.id
    create_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_object_rejected_by_destructive_reviewer(monkeypatch):
    """When ``ctx.llm_client`` is wired and the reviewer returns REJECT,
    the delete tool raises ToolDenied → ToolExecutionResult.status='denied'.
    Service-level delete must never be called."""
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Important")
    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    monkeypatch.setattr(
        "app.services.object_service.get_dependencies",
        AsyncMock(return_value={"upstream": [], "downstream": []}),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams_containing_object",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagrams",
        AsyncMock(return_value=[]),
    )
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.object_service.delete_object", delete_mock
    )

    # Stub the reviewer to return REJECT.
    from app.agents.tools import _destructive_review

    monkeypatch.setattr(
        _destructive_review,
        "review_destructive_op",
        AsyncMock(
            return_value=_destructive_review.DeleteVerdict(
                verdict="REJECT",
                rationale="agent created this object 2 steps ago — looks like churn",
            )
        ),
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "creject",
            "name": "delete_object",
            "arguments": {
                "object_id": str(obj.id),
                "confirmed": True,
                "reason": "no longer needed",
            },
        },
        ctx,
    )
    assert out.status == "denied"
    assert "reviewer rejected" in out.content
    delete_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_object_missing_reason_validation_error(monkeypatch):
    _patch_acl_pass(monkeypatch)
    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "cmissreason",
            "name": "delete_object",
            "arguments": {"object_id": str(uuid4()), "confirmed": True},
        },
        ctx,
    )
    assert out.status == "error"
    assert "reason" in out.content.lower()


@pytest.mark.asyncio
async def test_delete_diagram_preview_then_confirmed(monkeypatch):
    _patch_acl_pass(monkeypatch)

    diagram = _make_diagram_row(name="Old")
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=diagram),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram_objects",
        AsyncMock(return_value=[_make_placement(), _make_placement()]),
    )
    delete_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.diagram_service.delete_diagram", delete_mock
    )

    ctx = _ctx()
    out1 = await execute_tool(
        {
            "id": "c14",
            "name": "delete_diagram",
            "arguments": {
                "diagram_id": str(diagram.id),
                "confirmed": False,
                "reason": "removing obsolete L3 child diagram",
            },
        },
        ctx,
    )
    assert out1.status == "awaiting_confirmation"
    assert out1.raw["impact"]["will_drop_placements"] == 2
    delete_mock.assert_not_called()

    out2 = await execute_tool(
        {
            "id": "c15",
            "name": "delete_diagram",
            "arguments": {
                "diagram_id": str(diagram.id),
                "confirmed": True,
                "reason": "removing obsolete L3 child diagram",
            },
        },
        ctx,
    )
    assert out2.status == "ok", out2.content
    assert out2.structured.get("action") == "diagram.deleted"
    delete_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# View tools — hierarchy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_object_to_child_diagram_happy(monkeypatch):
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Order Svc")
    child = _make_diagram_row(name="Order Components")
    updated = _make_diagram_row(
        id=child.id, name=child.name, scope_object_id=obj.id
    )

    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    monkeypatch.setattr(
        "app.services.diagram_service.get_diagram",
        AsyncMock(return_value=child),
    )
    update_mock = AsyncMock(return_value=updated)
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram", update_mock
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c16",
            "name": "link_object_to_child_diagram",
            "arguments": {
                "object_id": str(obj.id),
                "child_diagram_id": str(child.id),
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.raw["linked_to_object_id"] == obj.id
    update_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_child_diagram_for_object_atomic(monkeypatch):
    """Composite tool: creates a diagram + sets scope_object_id in one go."""
    _patch_acl_pass(monkeypatch)

    obj = _make_object_row(name="Order Svc")
    obj.c4_level = "L2"

    new_diag = _make_diagram_row(
        name="Order Svc components", scope_object_id=obj.id
    )

    monkeypatch.setattr(
        "app.services.object_service.get_object",
        AsyncMock(return_value=obj),
    )
    create_mock = AsyncMock(return_value=new_diag)
    monkeypatch.setattr(
        "app.services.diagram_service.create_diagram", create_mock
    )

    ctx = _ctx()
    out = await execute_tool(
        {
            "id": "c17",
            "name": "create_child_diagram_for_object",
            "arguments": {"object_id": str(obj.id)},
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "diagram.created"
    assert out.raw["linked_to_object_id"] == obj.id
    # Verify scope_object_id was set on creation (single atomic call).
    create_mock.assert_awaited_once()
    call_args = create_mock.await_args
    create_payload = call_args.args[1]
    assert create_payload.scope_object_id == obj.id
    # Default level is one deeper than parent's L2 → L3 → component diagram.
    assert create_payload.type.value == "component"


# ---------------------------------------------------------------------------
# Registry assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,expected_scope",
    [
        ("create_object", "agents:write"),
        ("update_object", "agents:write"),
        ("delete_object", "agents:admin"),
        ("create_connection", "agents:write"),
        ("update_connection", "agents:write"),
        ("delete_connection", "agents:admin"),
        ("place_on_diagram", "agents:write"),
        ("move_on_diagram", "agents:write"),
        ("unplace_from_diagram", "agents:admin"),
        ("create_diagram", "agents:write"),
        ("update_diagram", "agents:write"),
        ("delete_diagram", "agents:admin"),
        ("link_object_to_child_diagram", "agents:write"),
        ("unlink_object_from_child_diagram", "agents:write"),
        ("create_child_diagram_for_object", "agents:admin"),
    ],
)
def test_write_tools_registered_with_correct_scope(tool_name, expected_scope):
    t = get_tool(tool_name)
    assert t.mutating is True
    assert t.required_scope == expected_scope
