"""Tests for batch_layout, layout metrics, and the auto_layout_diagram tool.

Spec reference: agent-core-mvp-054 / spec §7.5.

These tests mock ``db.execute`` so we don't need a real database — we feed
the engine pre-built ``DiagramObject`` / ``ModelObject`` / ``Connection``
ORM-like rows in the right shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import networkx as nx
import pytest

import app.agents.tools.model_tools as model_tools  # noqa: F401  — register tools
import app.agents.tools.view_tools as view_tools  # noqa: F401  — register tools
from app.agents.layout import metrics as layout_metrics
from app.agents.layout.conflict import BBox
from app.agents.layout.engine import (
    DEFAULT_CANVAS_SIZE,
    BatchLayoutPlan,
    _group_by_lane,
    _topological_order_within_lane,
    batch_layout,
)
from app.agents.tools.base import (
    ToolContext,
    clear_tools,
    execute_tool,
    get_tool,
    register_tool,
)

# ---------------------------------------------------------------------------
# Fakes (DB rows the engine inspects)
# ---------------------------------------------------------------------------


@dataclass
class _FakeDiagram:
    id: UUID
    type: Any  # MagicMock(value='system_context') etc.


@dataclass
class _FakeObject:
    id: UUID
    type: Any  # MagicMock(value='actor') etc.


@dataclass
class _FakeConnection:
    id: UUID
    source_id: UUID
    target_id: UUID


@dataclass
class _FakePlacement:
    diagram_id: UUID
    object_id: UUID
    position_x: float | None = 0.0
    position_y: float | None = 0.0
    width: float | None = None
    height: float | None = None


# ---------------------------------------------------------------------------
# Fake AsyncSession
# ---------------------------------------------------------------------------


class _ScalarsResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _ExecResult:
    def __init__(self, *, scalar_one: Any | None = None, items: list[Any] | None = None):
        self._scalar_one = scalar_one
        self._items = items or []

    def scalar_one(self) -> Any:
        if self._scalar_one is None:
            raise RuntimeError("no scalar_one configured")
        return self._scalar_one

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._items)


@dataclass
class _FakeSession:
    """Records execute() calls and returns canned results in order.

    The tests pre-load ``responses`` (a list of ``_ExecResult``) and execute
    pops the next one.  This is order-sensitive but mirrors the actual
    sequence in :func:`batch_layout`:

      1. ``select(Diagram)`` → diagram row (scalar_one)
      2. ``select(DiagramObject)`` → placements (scalars().all())
      3. ``select(ModelObject)`` → objects (scalars().all())
      4. ``select(Connection)`` → connections (scalars().all())
    """

    responses: list[_ExecResult] = field(default_factory=list)
    _calls: int = 0
    added: list[Any] = field(default_factory=list)

    async def execute(self, *_args, **_kwargs):
        if self._calls >= len(self.responses):
            raise AssertionError(
                f"unexpected execute call #{self._calls + 1}; only "
                f"{len(self.responses)} responses configured"
            )
        result = self.responses[self._calls]
        self._calls += 1
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


def _enum(value: str) -> Any:
    return MagicMock(value=value)


def _diagram(diagram_id: UUID, type_value: str = "system_context") -> _FakeDiagram:
    return _FakeDiagram(id=diagram_id, type=_enum(type_value))


def _object(object_id: UUID, type_value: str) -> _FakeObject:
    return _FakeObject(id=object_id, type=_enum(type_value))


def _placement(
    diagram_id: UUID,
    object_id: UUID,
    *,
    x: float = 0.0,
    y: float = 0.0,
    w: float | None = None,
    h: float | None = None,
) -> _FakePlacement:
    return _FakePlacement(
        diagram_id=diagram_id,
        object_id=object_id,
        position_x=x,
        position_y=y,
        width=w,
        height=h,
    )


def _build_session(
    *,
    diagram: _FakeDiagram,
    placements: list[_FakePlacement],
    objects: list[_FakeObject],
    connections: list[_FakeConnection],
) -> _FakeSession:
    responses = [
        _ExecResult(scalar_one=diagram),
        _ExecResult(items=placements),
    ]
    if placements:
        # batch_layout only fetches objects + connections when there are placements.
        responses.append(_ExecResult(items=objects))
        responses.append(_ExecResult(items=connections))
    return _FakeSession(responses=responses)


# ---------------------------------------------------------------------------
# batch_layout — high-level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_layout_empty_diagram_returns_empty_plan():
    diagram_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    session = _build_session(
        diagram=diagram, placements=[], objects=[], connections=[]
    )
    plan = await batch_layout(session, diagram_id=diagram_id, scope="all")
    assert isinstance(plan, BatchLayoutPlan)
    assert plan.moves == []
    assert plan.placements_full == {}
    assert "overlap_count" in plan.metrics


@pytest.mark.asyncio
async def test_batch_layout_three_actors_four_apps_no_overlap():
    """Context diagram: actors → top, systems → middle. No overlaps."""
    diagram_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")  # → L1 → context-diagram

    # 3 actors, 3 internal systems (becomes "middle", "center")
    actor_ids = [uuid4() for _ in range(3)]
    system_ids = [uuid4() for _ in range(3)]
    objects = [_object(i, "actor") for i in actor_ids] + [
        _object(i, "system") for i in system_ids
    ]
    placements = [_placement(diagram_id, o.id) for o in objects]
    plan = await batch_layout(
        _build_session(
            diagram=diagram,
            placements=placements,
            objects=objects,
            connections=[],
        ),
        diagram_id=diagram_id,
        scope="all",
    )
    assert plan.metrics["overlap_count"] == 0
    # All 6 must have placements.
    assert len(plan.placements_full) == 6
    # Actors should land in the top band (centre y < canvas_h/3).
    canvas_h = DEFAULT_CANVAS_SIZE[1]
    band = canvas_h / 3
    for aid in actor_ids:
        p = plan.placements_full[aid]
        assert p.y + p.h / 2 < band, f"actor {aid} not in top band: y={p.y}"


@pytest.mark.asyncio
async def test_batch_layout_microservices_pattern_respects_lane_convention():
    """L2/app-diagram with 5 apps + 1 store: apps in middle, store in bottom."""
    diagram_id = uuid4()
    diagram = _diagram(diagram_id, "container")  # → L2 → app-diagram

    apps = [_object(uuid4(), "app") for _ in range(5)]
    store = _object(uuid4(), "store")
    objects = apps + [store]
    placements = [_placement(diagram_id, o.id) for o in objects]
    plan = await batch_layout(
        _build_session(
            diagram=diagram, placements=placements, objects=objects, connections=[]
        ),
        diagram_id=diagram_id,
        scope="all",
    )
    canvas_h = DEFAULT_CANVAS_SIZE[1]
    band = canvas_h / 3
    # Apps: middle band.
    for app in apps:
        p = plan.placements_full[app.id]
        cy = p.y + p.h / 2
        assert band <= cy < 2 * band, f"app not in middle band: y={p.y}"
    # Store: bottom band.
    sp = plan.placements_full[store.id]
    cy = sp.y + sp.h / 2
    assert cy >= 2 * band, f"store not in bottom band: y={sp.y}"


@pytest.mark.asyncio
async def test_batch_layout_new_only_preserves_existing_positions():
    """scope='new_only' — every placement already has (x, y); none should move."""
    diagram_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    actor = _object(uuid4(), "actor")
    sys_ = _object(uuid4(), "system")
    placements = [
        _placement(diagram_id, actor.id, x=512, y=64, w=192, h=112),
        _placement(diagram_id, sys_.id, x=512, y=720, w=256, h=128),
    ]
    plan = await batch_layout(
        _build_session(
            diagram=diagram,
            placements=placements,
            objects=[actor, sys_],
            connections=[],
        ),
        diagram_id=diagram_id,
        scope="new_only",
    )
    # No moves — both rows already had x/y set.
    assert plan.moves == []
    assert plan.placements_full[actor.id].x == 512
    assert plan.placements_full[actor.id].y == 64


@pytest.mark.asyncio
async def test_batch_layout_all_replaces_all_positions():
    """scope='all' rewrites every position even when objects are already placed."""
    diagram_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    actor = _object(uuid4(), "actor")
    placements = [
        _placement(diagram_id, actor.id, x=99999, y=99999, w=192, h=112),
    ]
    plan = await batch_layout(
        _build_session(
            diagram=diagram,
            placements=placements,
            objects=[actor],
            connections=[],
        ),
        diagram_id=diagram_id,
        scope="all",
    )
    # The actor was at (99999, 99999); after batch_layout it should be inside
    # the canvas (x < 2400, y < 1600 / 3).
    new = plan.placements_full[actor.id]
    assert new.x != 99999 or new.y != 99999
    assert len(plan.moves) == 1
    moved_id, _, _ = plan.moves[0]
    assert moved_id == actor.id


# ---------------------------------------------------------------------------
# Helpers — _topological_order_within_lane / _group_by_lane
# ---------------------------------------------------------------------------


def test_topological_order_cycle_falls_back_to_input_order():
    a, b, c = uuid4(), uuid4(), uuid4()
    g = nx.DiGraph()
    g.add_edge(a, b)
    g.add_edge(b, c)
    g.add_edge(c, a)  # cycle
    out = _topological_order_within_lane(g, [a, b, c])
    assert out == [a, b, c]  # fallback preserves input order


def test_topological_order_dag_orders_predecessors_first():
    a, b, c = uuid4(), uuid4(), uuid4()
    g = nx.DiGraph()
    g.add_edge(a, b)
    g.add_edge(b, c)
    out = _topological_order_within_lane(g, [c, a, b])
    assert out.index(a) < out.index(b) < out.index(c)


def test_group_by_lane_routes_any_to_middle():
    a, b, c = uuid4(), uuid4(), uuid4()
    hints = {
        a: {"row": "top"},
        b: {"row": "any"},
        c: {},  # missing row → middle
    }
    groups = _group_by_lane([a, b, c], hints)
    assert groups.get("top") == [a]
    assert set(groups.get("middle", [])) == {b, c}


# ---------------------------------------------------------------------------
# metrics.py
# ---------------------------------------------------------------------------


def test_overlap_count_two_overlapping_bboxes_returns_one():
    # Two boxes sharing the same area.
    a = BBox(0, 0, 100, 100)
    b = BBox(50, 50, 100, 100)
    assert layout_metrics.overlap_count([a, b], clearance=0) == 1


def test_overlap_count_zero_when_far_apart():
    a = BBox(0, 0, 100, 100)
    b = BBox(500, 500, 100, 100)
    assert layout_metrics.overlap_count([a, b], clearance=24) == 0


def test_edge_crossings_known_crossing_pattern():
    """Two edges that visibly cross."""
    a = BBox(0, 0, 10, 10)
    b = BBox(100, 0, 10, 10)
    c = BBox(0, 100, 10, 10)
    d = BBox(100, 100, 10, 10)
    # a-d and b-c cross diagonally.
    assert layout_metrics.edge_crossings([(a, d), (b, c)]) == 1


def test_edge_crossings_parallel_no_cross():
    a = BBox(0, 0, 10, 10)
    b = BBox(100, 0, 10, 10)
    c = BBox(0, 50, 10, 10)
    d = BBox(100, 50, 10, 10)
    # Two parallel horizontal edges.
    assert layout_metrics.edge_crossings([(a, b), (c, d)]) == 0


def test_lane_violations_object_in_wrong_lane_counted():
    oid = uuid4()
    # canvas height 1500 → bands at 500 / 1000.
    # Object claims top (row=top) but its centre is at y=1200 (bottom band).
    bbox = BBox(0, 1180, 100, 40)  # centre y = 1200
    placements = {oid: bbox}
    hints = {oid: {"row": "top"}}
    assert layout_metrics.lane_violations(
        placements, hints, canvas_size=(2000, 1500)
    ) == 1


def test_lane_violations_zero_when_lane_matches():
    oid = uuid4()
    bbox = BBox(0, 100, 100, 40)  # centre y=120, top band
    placements = {oid: bbox}
    hints = {oid: {"row": "top"}}
    assert layout_metrics.lane_violations(
        placements, hints, canvas_size=(2000, 1500)
    ) == 0


def test_grid_alignment_violations_x_15_counted():
    a = BBox(15, 0, 100, 100)
    b = BBox(16, 16, 100, 100)
    c = BBox(0, 17, 100, 100)
    assert layout_metrics.grid_alignment_violations([a, b, c], step=16) == 2


def test_grid_alignment_violations_zero_when_aligned():
    a = BBox(0, 0, 100, 100)
    b = BBox(64, 128, 100, 100)
    assert layout_metrics.grid_alignment_violations([a, b], step=16) == 0


def test_compactness_returns_value_between_zero_and_one():
    a = BBox(0, 0, 100, 100)
    b = BBox(100, 0, 100, 100)
    score = layout_metrics.compactness([a, b])
    assert 0.0 <= score <= 1.0


def test_lane_balance_uniform_gives_zero():
    a = BBox(0, 0, 100, 100)
    by_lane = {"top": [a], "middle": [a], "bottom": [a]}
    assert layout_metrics.lane_balance(by_lane) == 0.0


def test_layout_score_empty_inputs_safe():
    out = layout_metrics.layout_score([], [], {}, (2400, 1600))
    assert out["overlap_count"] == 0
    assert out["edge_crossings"] == 0
    assert out["grid_alignment_violations"] == 0
    assert out["lane_violations"] == 0


# ---------------------------------------------------------------------------
# auto_layout_diagram tool wrapper
# ---------------------------------------------------------------------------


@dataclass
class _FakeActor:
    kind: str = "user"
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID = field(default_factory=uuid4)
    scopes: tuple[str, ...] = ()
    role: Any = None


def _ctx(*, db: _FakeSession | None = None) -> ToolContext:
    ws = uuid4()
    actor = _FakeActor(workspace_id=ws)
    return ToolContext(
        db=db or _FakeSession(),
        actor=actor,
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


def _patch_acl_pass(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.fixture(autouse=True)
def _ensure_tools_registered():
    """Re-register every Tool from view_tools/model_tools after any clear."""
    from app.agents.tools.base import Tool as _Tool

    clear_tools()
    for module in (model_tools, view_tools):
        for attr in vars(module).values():
            if isinstance(attr, _Tool):
                register_tool(attr)
    yield
    clear_tools()


@pytest.mark.asyncio
async def test_auto_layout_diagram_scope_all_without_confirmed_returns_awaiting(monkeypatch):
    """scope='all' without confirmed=True must return awaiting_confirmation."""
    _patch_acl_pass(monkeypatch)

    diagram_id = uuid4()
    actor_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    obj = _object(actor_id, "actor")
    placements = [_placement(diagram_id, actor_id, x=100, y=100, w=192, h=112)]

    fake_session = _build_session(
        diagram=diagram, placements=placements, objects=[obj], connections=[]
    )

    ctx = _ctx(db=fake_session)
    out = await execute_tool(
        {
            "id": "c1",
            "name": "auto_layout_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "scope": "all",
            },
        },
        ctx,
    )
    assert out.status == "awaiting_confirmation", out.content


@pytest.mark.asyncio
async def test_auto_layout_diagram_dry_run_does_not_write(monkeypatch):
    _patch_acl_pass(monkeypatch)

    diagram_id = uuid4()
    actor_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    obj = _object(actor_id, "actor")
    placements = [_placement(diagram_id, actor_id, x=99999, y=99999, w=192, h=112)]
    fake_session = _build_session(
        diagram=diagram, placements=placements, objects=[obj], connections=[]
    )

    update_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram_object", update_mock
    )

    ctx = _ctx(db=fake_session)
    out = await execute_tool(
        {
            "id": "c2",
            "name": "auto_layout_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "scope": "all",
                "dry_run": True,
                "confirmed": True,  # bypass gate even in dry_run path
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    update_mock.assert_not_awaited()
    assert "moves" in out.raw
    assert out.raw.get("dry_run") is True


@pytest.mark.asyncio
async def test_auto_layout_diagram_new_only_applies_moves(monkeypatch):
    """scope='new_only' with already-placed objects → no moves to apply, ok status."""
    _patch_acl_pass(monkeypatch)

    diagram_id = uuid4()
    actor_id = uuid4()
    diagram = _diagram(diagram_id, "system_context")
    obj = _object(actor_id, "actor")
    placements = [_placement(diagram_id, actor_id, x=512, y=64, w=192, h=112)]
    fake_session = _build_session(
        diagram=diagram, placements=placements, objects=[obj], connections=[]
    )

    update_mock = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        "app.services.diagram_service.update_diagram_object", update_mock
    )

    ctx = _ctx(db=fake_session)
    out = await execute_tool(
        {
            "id": "c3",
            "name": "auto_layout_diagram",
            "arguments": {
                "diagram_id": str(diagram_id),
                "scope": "new_only",
            },
        },
        ctx,
    )
    assert out.status == "ok", out.content
    assert out.structured.get("action") == "diagram.relayouted"
    # All placements already had positions → no moves applied.
    assert out.raw.get("moves_applied") == 0


def test_auto_layout_diagram_registered_with_correct_scope():
    t = get_tool("auto_layout_diagram")
    assert t.mutating is True
    assert t.required_scope == "agents:write"
    assert t.required_permission == "diagram:edit"
    assert t.permission_target == "diagram"
