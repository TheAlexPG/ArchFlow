"""Tests for app/agents/tools/model_tools.py — read tools (task agent-core-mvp-027).

All tools are tested with mocked/stubbed services — no real DB or LLM required.

Each @tool-decorated function returns a Tool instance; we call .handler(args, ctx)
directly to bypass the execute_tool wrapper (which would trigger ACL etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Import module to trigger @tool decorator registrations.
import app.agents.tools.model_tools  # noqa: F401
from app.agents.tools.base import ToolContext, clear_tools, get_tool, register_tool
from app.agents.tools.model_tools import (
    DependenciesInput,
    ListChildDiagramsInput,
    ListDiagramsInput,
    ListObjectsInput,
    ReadCanvasStateInput,
    ReadChildDiagramInput,
    ReadConnectionInput,
    ReadDiagramInput,
    ReadObjectFullInput,
    ReadObjectInput,
    _project_connection,
    _project_object_basic,
    _project_object_full,
    _strip_html,
    dependencies,
    list_child_diagrams,
    list_diagrams,
    list_objects,
    read_canvas_state,
    read_child_diagram,
    read_connection,
    read_diagram,
    read_object,
    read_object_full,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    workspace_id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeResult:
    """A flexible mock for AsyncSession.execute() return value."""

    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self) -> Any:
        m = MagicMock()
        m.all.return_value = list(self._rows)
        return m

    def scalar_one_or_none(self) -> Any | None:
        return self._scalar

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """AsyncSession stub that pops from a preset result queue."""

    def __init__(self) -> None:
        self._results: list[FakeResult] = []
        self._call_idx = 0
        self.added: list[Any] = []
        self.flush_count = 0

    def queue(self, rows: list[Any] | None = None, scalar: Any = None) -> FakeSession:
        self._results.append(FakeResult(rows=rows, scalar=scalar))
        return self

    async def execute(self, stmt: Any) -> FakeResult:
        if self._call_idx < len(self._results):
            result = self._results[self._call_idx]
            self._call_idx += 1
            return result
        return FakeResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1


def _make_ctx(
    db: FakeSession | None = None,
    workspace_id: UUID | None = None,
) -> ToolContext:
    ws = workspace_id or uuid4()
    return ToolContext(
        db=db or FakeSession(),
        actor=FakeActor(kind="user", id=uuid4(), workspace_id=ws),
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": str(ws)},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


def _make_object(
    *,
    object_id: UUID | None = None,
    name: str = "Order Service",
    obj_type: str = "system",
    parent_id: UUID | None = None,
    technology_ids: list[UUID] | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    owner_team: str | None = None,
    status: str = "live",
    scope: str = "internal",
) -> MagicMock:
    obj = MagicMock()
    obj.id = object_id or uuid4()
    obj.name = name
    type_mock = MagicMock()
    type_mock.value = obj_type
    obj.type = type_mock
    obj.parent_id = parent_id
    obj.technology_ids = technology_ids or []
    obj.description = description
    obj.tags = tags or []
    obj.owner_team = owner_team
    status_mock = MagicMock()
    status_mock.value = status
    obj.status = status_mock
    scope_mock = MagicMock()
    scope_mock.value = scope
    obj.scope = scope_mock
    obj.created_at = "2026-01-01T00:00:00"
    obj.updated_at = "2026-01-02T00:00:00"
    obj._has_child_diagram = False
    return obj


def _make_connection(
    *,
    conn_id: UUID | None = None,
    source_id: UUID | None = None,
    target_id: UUID | None = None,
    label: str | None = "calls",
    protocol_ids: list[UUID] | None = None,
    direction: str = "unidirectional",
) -> MagicMock:
    conn = MagicMock()
    conn.id = conn_id or uuid4()
    conn.source_id = source_id or uuid4()
    conn.target_id = target_id or uuid4()
    conn.label = label
    conn.protocol_ids = protocol_ids or []
    direction_mock = MagicMock()
    direction_mock.value = direction
    conn.direction = direction_mock
    return conn


def _make_diagram(
    *,
    diagram_id: UUID | None = None,
    name: str = "System Context",
    diagram_type: str = "system_context",
    scope_object_id: UUID | None = None,
    workspace_id: UUID | None = None,
    placements: list[Any] | None = None,
) -> MagicMock:
    d = MagicMock()
    d.id = diagram_id or uuid4()
    d.name = name
    type_mock = MagicMock()
    type_mock.value = diagram_type
    d.type = type_mock
    d.description = None
    d.scope_object_id = scope_object_id
    d.workspace_id = workspace_id or uuid4()
    d.objects = placements or []
    return d


def _make_placement(
    *,
    object_id: UUID | None = None,
    x: float = 100.0,
    y: float = 200.0,
    width: float | None = 192.0,
    height: float | None = 112.0,
) -> MagicMock:
    p = MagicMock()
    p.object_id = object_id or uuid4()
    p.position_x = x
    p.position_y = y
    p.width = width
    p.height = height
    return p


@pytest.fixture(autouse=True)
def _reset_and_reload_registry():
    """Clear registry before each test; re-register read tools from model_tools."""
    clear_tools()
    # The @tool decorators ran at import time, leaving Tool objects as module-level
    # names. Re-register all of them so get_tool() works in registration tests.
    tools_to_register = [
        read_object,
        read_object_full,
        read_connection,
        dependencies,
        list_objects,
        list_diagrams,
        read_diagram,
        read_canvas_state,
        list_child_diagrams,
        read_child_diagram,
    ]
    for t in tools_to_register:
        register_tool(t)
    yield
    clear_tools()


# ---------------------------------------------------------------------------
# 1. read_object happy path — returns projected dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_object_happy_path():
    """read_object returns id, name, type, parent_id, has_child_diagram."""
    oid = uuid4()
    obj = _make_object(object_id=oid, name="API Gateway", obj_type="app")
    obj._has_child_diagram = True

    ctx = _make_ctx()

    with patch(
        "app.agents.tools.model_tools._get_object_with_child_flag",
        new=AsyncMock(return_value=obj),
    ):
        result = await read_object.handler(ReadObjectInput(object_id=oid), ctx)

    assert result["id"] == str(oid)
    assert result["name"] == "API Gateway"
    assert result["type"] == "app"
    assert result["has_child_diagram"] is True
    # Should NOT include description or owner
    assert "description" not in result
    assert "owner_team" not in result


@pytest.mark.asyncio
async def test_read_object_not_found():
    ctx = _make_ctx()
    oid = uuid4()

    with patch(
        "app.agents.tools.model_tools._get_object_with_child_flag",
        new=AsyncMock(return_value=None),
    ):
        result = await read_object.handler(ReadObjectInput(object_id=oid), ctx)

    assert result["error"] == "object_not_found"
    assert result["object_id"] == str(oid)


# ---------------------------------------------------------------------------
# 2. read_object_full — includes plain-text description, excludes HTML
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_object_full_plain_text_description():
    """read_object_full strips HTML tags and returns plain-text description."""
    oid = uuid4()
    obj = _make_object(
        object_id=oid,
        name="Payments Service",
        description="<p>Handles <b>all</b> payment processing.</p>",
        tags=["core", "payments"],
        owner_team="platform",
    )
    obj._has_child_diagram = False

    ctx = _make_ctx()

    with patch(
        "app.agents.tools.model_tools._get_object_with_child_flag",
        new=AsyncMock(return_value=obj),
    ):
        result = await read_object_full.handler(ReadObjectFullInput(object_id=oid), ctx)

    assert result["id"] == str(oid)
    assert "description_html" not in result
    assert "<p>" not in result["description"]
    assert "<b>" not in result["description"]
    assert "all" in result["description"]
    assert "Handles" in result["description"]
    assert result["tags"] == ["core", "payments"]
    assert result["owner_team"] == "platform"
    assert "created_at" in result
    assert "updated_at" in result


@pytest.mark.asyncio
async def test_read_object_full_null_description():
    """read_object_full returns empty string when description is None."""
    oid = uuid4()
    obj = _make_object(object_id=oid, description=None)
    obj._has_child_diagram = False

    ctx = _make_ctx()

    with patch(
        "app.agents.tools.model_tools._get_object_with_child_flag",
        new=AsyncMock(return_value=obj),
    ):
        result = await read_object_full.handler(ReadObjectFullInput(object_id=oid), ctx)

    assert result["description"] == ""


# ---------------------------------------------------------------------------
# 3. read_connection happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_connection_happy_path():
    conn_id = uuid4()
    src_id = uuid4()
    tgt_id = uuid4()
    tech_id = uuid4()
    conn = _make_connection(
        conn_id=conn_id,
        source_id=src_id,
        target_id=tgt_id,
        label="HTTPS",
        protocol_ids=[tech_id],
    )

    ctx = _make_ctx()

    with patch(
        "app.services.connection_service.get_connection",
        new=AsyncMock(return_value=conn),
    ):
        result = await read_connection.handler(
            ReadConnectionInput(connection_id=conn_id), ctx
        )

    assert result["id"] == str(conn_id)
    assert result["source_id"] == str(src_id)
    assert result["target_id"] == str(tgt_id)
    assert result["label"] == "HTTPS"
    assert str(tech_id) in result["technology_ids"]


@pytest.mark.asyncio
async def test_read_connection_not_found():
    ctx = _make_ctx()
    cid = uuid4()

    with patch(
        "app.services.connection_service.get_connection",
        new=AsyncMock(return_value=None),
    ):
        result = await read_connection.handler(
            ReadConnectionInput(connection_id=cid), ctx
        )

    assert result["error"] == "connection_not_found"


# ---------------------------------------------------------------------------
# 4. dependencies — returns upstream/downstream lists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dependencies_returns_upstream_downstream():
    oid = uuid4()
    src_id = uuid4()
    tgt_id = uuid4()

    upstream_conn = _make_connection(source_id=src_id, target_id=oid, label="feeds")
    downstream_conn = _make_connection(source_id=oid, target_id=tgt_id, label="calls")

    deps_result = {"upstream": [upstream_conn], "downstream": [downstream_conn]}

    ctx = _make_ctx()

    with patch(
        "app.services.object_service.get_dependencies",
        new=AsyncMock(return_value=deps_result),
    ):
        result = await dependencies.handler(
            DependenciesInput(object_id=oid, depth=1), ctx
        )

    assert len(result["upstream"]) == 1
    assert result["upstream"][0]["target_id"] == str(oid)
    assert result["upstream"][0]["label"] == "feeds"
    assert len(result["downstream"]) == 1
    assert result["downstream"][0]["source_id"] == str(oid)
    assert result["downstream"][0]["label"] == "calls"


# ---------------------------------------------------------------------------
# 5. list_objects pagination — 50 items + cursor when 51 in DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_objects_pagination_cursor():
    """When DB has 51 objects with limit=50, next_cursor is returned."""
    ws_id = uuid4()
    ctx = _make_ctx(workspace_id=ws_id)

    # 51 mock objects to trigger pagination.
    objs = [_make_object(name=f"Obj{i}", obj_type="system") for i in range(51)]

    # First execute: list objects query (returns 51 — one past limit).
    # Second execute: batch child-diagram check (returns empty).
    execute_results = [
        FakeResult(rows=objs),
        # Child diagram check: all() returns list of (uuid,) pairs.
        _child_diagram_fake_result([]),
    ]
    ctx.db = FakeSession()

    with patch.object(
        ctx.db,
        "execute",
        new=AsyncMock(side_effect=execute_results),
    ):
        result = await list_objects.handler(
            ListObjectsInput(limit=50), ctx
        )

    assert len(result["items"]) == 50
    assert result["next_cursor"] is not None


def _child_diagram_fake_result(scope_ids: list[UUID]) -> Any:
    """Simulate the execute result for the child diagram batch query."""
    r = MagicMock()
    r.all.return_value = [(sid,) for sid in scope_ids]
    # scalars().all() not used for this query — it returns tuples via .all()
    r.scalars.return_value.all.return_value = scope_ids
    return r


@pytest.mark.asyncio
async def test_list_objects_no_next_cursor_when_exact_limit():
    """When DB returns exactly limit items, next_cursor is None."""
    ws_id = uuid4()
    ctx = _make_ctx(workspace_id=ws_id)
    objs = [_make_object(name=f"Obj{i}") for i in range(10)]

    with patch.object(
        ctx.db,
        "execute",
        new=AsyncMock(
            side_effect=[
                FakeResult(rows=objs),
                _child_diagram_fake_result([]),
            ]
        ),
    ):
        result = await list_objects.handler(
            ListObjectsInput(limit=10), ctx
        )

    assert result["next_cursor"] is None
    assert len(result["items"]) == 10


# ---------------------------------------------------------------------------
# 6. list_objects filter by types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_objects_filter_by_types():
    """list_objects with types filter returns only projected items."""
    ws_id = uuid4()
    ctx = _make_ctx(workspace_id=ws_id)

    system_obj = _make_object(name="API GW", obj_type="system")
    objs = [system_obj]

    with patch.object(
        ctx.db,
        "execute",
        new=AsyncMock(
            side_effect=[
                FakeResult(rows=objs),
                _child_diagram_fake_result([]),
            ]
        ),
    ):
        result = await list_objects.handler(
            ListObjectsInput(types=["system"], limit=50), ctx
        )

    assert len(result["items"]) == 1
    assert result["items"][0]["type"] == "system"


# ---------------------------------------------------------------------------
# 7. list_diagrams happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_diagrams_happy_path():
    ws_id = uuid4()
    ctx = _make_ctx(workspace_id=ws_id)

    diag = _make_diagram(name="Payments Context", workspace_id=ws_id)

    with patch.object(
        ctx.db,
        "execute",
        new=AsyncMock(return_value=FakeResult(rows=[diag])),
    ):
        result = await list_diagrams.handler(
            ListDiagramsInput(limit=50), ctx
        )

    assert len(result["items"]) == 1
    assert result["items"][0]["name"] == "Payments Context"
    assert result["next_cursor"] is None


# ---------------------------------------------------------------------------
# 8. read_diagram — returns placements + connections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_diagram_returns_placements_and_connections():
    diagram_id = uuid4()
    oid1, oid2 = uuid4(), uuid4()

    p1 = _make_placement(object_id=oid1, x=100, y=200)
    p2 = _make_placement(object_id=oid2, x=400, y=200)
    diagram = _make_diagram(diagram_id=diagram_id, placements=[p1, p2])

    conn = _make_connection(source_id=oid1, target_id=oid2)

    ctx = _make_ctx()

    with (
        patch(
            "app.services.diagram_service.get_diagram",
            new=AsyncMock(return_value=diagram),
        ),
        patch(
            "app.agents.tools.model_tools._get_diagram_connections",
            new=AsyncMock(return_value=[conn]),
        ),
    ):
        result = await read_diagram.handler(ReadDiagramInput(diagram_id=diagram_id), ctx)

    assert result["id"] == str(diagram_id)
    assert len(result["placements"]) == 2
    assert result["placements"][0]["object_id"] == str(oid1)
    assert result["placements"][0]["x"] == 100.0
    assert result["placements"][0]["y"] == 200.0
    assert len(result["connections"]) == 1
    assert result["connections"][0]["source_id"] == str(oid1)
    assert result["connections"][0]["target_id"] == str(oid2)


@pytest.mark.asyncio
async def test_read_diagram_truncates_placements_at_50():
    """Diagrams with > 50 objects get a _truncated marker appended."""
    diagram_id = uuid4()
    placements = [_make_placement() for _ in range(60)]
    diagram = _make_diagram(diagram_id=diagram_id, placements=placements)

    ctx = _make_ctx()

    with (
        patch(
            "app.services.diagram_service.get_diagram",
            new=AsyncMock(return_value=diagram),
        ),
        patch(
            "app.agents.tools.model_tools._get_diagram_connections",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await read_diagram.handler(ReadDiagramInput(diagram_id=diagram_id), ctx)

    # 50 real + 1 _truncated marker
    assert len(result["placements"]) == 51
    last = result["placements"][-1]
    assert "_truncated" in last
    assert last["_truncated"] == 10


# ---------------------------------------------------------------------------
# 9. read_canvas_state — minimal shape, no description_html
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_canvas_state_minimal_shape():
    diagram_id = uuid4()
    oid = uuid4()

    p = _make_placement(object_id=oid, x=50, y=80, width=200, height=100)
    diagram = _make_diagram(diagram_id=diagram_id, placements=[p])

    obj = _make_object(object_id=oid, name="Cache", obj_type="store")

    obj_execute_result = MagicMock()
    obj_execute_result.scalars.return_value.all.return_value = [obj]

    ctx = _make_ctx()

    with (
        patch(
            "app.services.diagram_service.get_diagram",
            new=AsyncMock(return_value=diagram),
        ),
        patch.object(
            ctx.db,
            "execute",
            new=AsyncMock(return_value=obj_execute_result),
        ),
        patch(
            "app.agents.tools.model_tools._get_diagram_connections",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await read_canvas_state.handler(
            ReadCanvasStateInput(diagram_id=diagram_id), ctx
        )

    assert "diagram_id" in result
    assert len(result["placements"]) == 1
    p_out = result["placements"][0]
    assert p_out["object_id"] == str(oid)
    assert p_out["x"] == 50.0
    assert p_out["y"] == 80.0
    assert p_out["w"] == 200.0
    assert p_out["h"] == 100.0
    assert p_out["name"] == "Cache"
    assert p_out["type"] == "store"
    # Must not leak description_html
    assert "description" not in p_out
    assert "description_html" not in p_out


# ---------------------------------------------------------------------------
# 10. list_child_diagrams — empty list when no children
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_child_diagrams_empty_when_no_children():
    oid = uuid4()
    ctx = _make_ctx()

    with patch(
        "app.services.diagram_service.get_diagrams",
        new=AsyncMock(return_value=[]),
    ):
        result = await list_child_diagrams.handler(
            ListChildDiagramsInput(object_id=oid), ctx
        )

    assert result == {"items": []}


@pytest.mark.asyncio
async def test_list_child_diagrams_returns_items():
    oid = uuid4()
    ctx = _make_ctx()
    child = _make_diagram(name="Container Diagram", scope_object_id=oid)

    with patch(
        "app.services.diagram_service.get_diagrams",
        new=AsyncMock(return_value=[child]),
    ):
        result = await list_child_diagrams.handler(
            ListChildDiagramsInput(object_id=oid), ctx
        )

    assert len(result["items"]) == 1
    assert result["items"][0]["scope_object_id"] == str(oid)


# ---------------------------------------------------------------------------
# 11. read_child_diagram delegates to read_diagram (smoke test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_child_diagram_delegates_to_read_diagram():
    diagram_id = uuid4()
    ctx = _make_ctx()
    diagram = _make_diagram(diagram_id=diagram_id, placements=[])

    with (
        patch(
            "app.services.diagram_service.get_diagram",
            new=AsyncMock(return_value=diagram),
        ),
        patch(
            "app.agents.tools.model_tools._get_diagram_connections",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await read_child_diagram.handler(
            ReadChildDiagramInput(diagram_id=diagram_id), ctx
        )

    # read_child_diagram just delegates — result has same shape as read_diagram.
    assert result["id"] == str(diagram_id)
    assert "placements" in result
    assert "connections" in result


# ---------------------------------------------------------------------------
# 12. Registration assertions — scope and mutating flags
# ---------------------------------------------------------------------------


def test_all_read_tools_registered_with_correct_scope_and_mutating():
    """Verify all read tools have required_scope='agents:read' and mutating=False."""
    read_tool_names = [
        "read_object",
        "read_object_full",
        "read_connection",
        "dependencies",
        "list_objects",
        "list_diagrams",
        "read_diagram",
        "read_canvas_state",
        "list_child_diagrams",
        "read_child_diagram",
    ]
    for name in read_tool_names:
        t = get_tool(name)
        assert t.required_scope == "agents:read", (
            f"{name}: expected required_scope='agents:read', got {t.required_scope!r}"
        )
        assert t.mutating is False, (
            f"{name}: expected mutating=False, got {t.mutating!r}"
        )


def test_read_object_tool_has_correct_permission():
    t = get_tool("read_object")
    assert t.required_permission == "diagram:read"
    assert t.permission_target == "object"


def test_list_objects_tool_has_workspace_permission():
    t = get_tool("list_objects")
    assert t.required_permission == "workspace:read"


# ---------------------------------------------------------------------------
# Projection helper unit tests
# ---------------------------------------------------------------------------


def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert _strip_html(None) == ""
    assert _strip_html("") == ""
    assert _strip_html("plain text") == "plain text"


def test_project_object_basic_excludes_description():
    obj = _make_object(
        name="X", obj_type="app", description="<p>secret</p>", owner_team="team-a"
    )
    obj._has_child_diagram = False
    proj = _project_object_basic(obj)
    assert "description" not in proj
    assert "owner_team" not in proj
    assert proj["name"] == "X"
    assert proj["type"] == "app"
    assert proj["has_child_diagram"] is False


def test_project_object_full_plain_text():
    obj = _make_object(
        name="Y",
        description="<em>Important</em> service",
        tags=["svc"],
        owner_team="backend",
    )
    obj._has_child_diagram = True
    proj = _project_object_full(obj)
    assert proj["description"] == "Important service"
    assert "description_html" not in proj
    assert proj["tags"] == ["svc"]
    assert proj["owner_team"] == "backend"


def test_project_connection_maps_protocol_ids_to_technology_ids():
    conn = _make_connection(protocol_ids=[uuid4(), uuid4()])
    proj = _project_connection(conn)
    assert len(proj["technology_ids"]) == 2
    assert "protocol_ids" not in proj
