"""Tests for the incremental placement engine (task agent-core-mvp-053).

Covers:
  * BBox.overlaps semantics (identical, touching, clearance).
  * first_free_slot empty / spiral / seed.
  * _compute_relatedness_seed weighted/unweighted average.
  * _lane_anchor hint mapping.
  * incremental_place end-to-end against a FakeSession backing store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from app.agents.layout.conflict import BBox, first_free_slot
from app.agents.layout.engine import (
    PlacementResult,
    _compute_relatedness_seed,
    _lane_anchor,
    incremental_place,
)
from app.agents.layout.grid import LANE_PADDING, default_size
from app.models.connection import Connection
from app.models.diagram import Diagram, DiagramObject, DiagramType
from app.models.object import ModelObject, ObjectType

# ---------------------------------------------------------------------------
# FakeSession — enough surface to satisfy incremental_place
# ---------------------------------------------------------------------------


@dataclass
class _FakeDiagramRow:
    id: UUID
    type: DiagramType


@dataclass
class _FakeObjectRow:
    id: UUID
    type: ObjectType


@dataclass
class _FakePlacementRow:
    id: UUID
    diagram_id: UUID
    object_id: UUID
    position_x: float
    position_y: float
    width: float | None
    height: float | None


@dataclass
class _FakeConnectionRow:
    id: UUID
    source_id: UUID
    target_id: UUID


@dataclass
class _FakeStore:
    diagrams: list[_FakeDiagramRow] = field(default_factory=list)
    objects: list[_FakeObjectRow] = field(default_factory=list)
    placements: list[_FakePlacementRow] = field(default_factory=list)
    connections: list[_FakeConnectionRow] = field(default_factory=list)


class _FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalar_one(self) -> Any:
        if not self._rows:
            raise RuntimeError("scalar_one() with no rows")
        return self._rows[0]

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Minimal AsyncSession stand-in.  Inspects the ORM target of select()
    and returns matching rows from the in-memory store."""

    def __init__(self, store: _FakeStore):
        self._store = store

    async def execute(self, stmt: Any) -> _FakeResult:
        # SQLAlchemy 2.0 ``select(Model)`` exposes the column descriptions
        # via .column_descriptions[0]['entity'].
        target = stmt.column_descriptions[0]["entity"]
        if target is Diagram:
            return _FakeResult(_filter_by_id(self._store.diagrams, stmt))
        if target is ModelObject:
            return _FakeResult(_filter_by_id(self._store.objects, stmt))
        if target is DiagramObject:
            return _FakeResult(_filter_placements(self._store.placements, stmt))
        if target is Connection:
            # incremental_place filters source_id == X OR target_id == X.
            # The fake just returns every connection — the engine then
            # cross-references with placement_by_object so this is safe.
            return _FakeResult(list(self._store.connections))
        raise AssertionError(f"unexpected select target: {target!r}")


def _filter_by_id(rows: list[Any], stmt: Any) -> list[Any]:
    """select(Model).where(Model.id == X) — just match by id from the WHERE clause."""
    target_id = _extract_eq(stmt, "id")
    if target_id is None:
        return list(rows)
    return [r for r in rows if r.id == target_id]


def _filter_placements(rows: list[_FakePlacementRow], stmt: Any) -> list[_FakePlacementRow]:
    diagram_id = _extract_eq(stmt, "diagram_id")
    object_ne = _extract_ne(stmt, "object_id")
    out = list(rows)
    if diagram_id is not None:
        out = [r for r in out if r.diagram_id == diagram_id]
    if object_ne is not None:
        out = [r for r in out if r.object_id != object_ne]
    return out


def _extract_eq(stmt: Any, attr: str) -> Any:
    """Walk the WHERE clause looking for ``Model.<attr> == value``."""
    for clause in stmt.whereclause.get_children() if stmt.whereclause is not None else []:
        if not hasattr(clause, "left") or not hasattr(clause, "right"):
            continue
        left_name = getattr(clause.left, "key", None)
        op = getattr(clause.operator, "__name__", "")
        if left_name == attr and op == "eq":
            return clause.right.value
    # Top-level binary expression with a single eq is also possible.
    where = stmt.whereclause
    if where is not None and hasattr(where, "left") and hasattr(where, "right"):
        left_name = getattr(where.left, "key", None)
        op = getattr(where.operator, "__name__", "")
        if left_name == attr and op == "eq":
            return where.right.value
    return None


def _extract_ne(stmt: Any, attr: str) -> Any:
    where = stmt.whereclause
    children = list(where.get_children()) if where is not None else []
    candidates = children + ([where] if where is not None else [])
    for clause in candidates:
        if not hasattr(clause, "left") or not hasattr(clause, "right"):
            continue
        left_name = getattr(clause.left, "key", None)
        op = getattr(clause.operator, "__name__", "")
        if left_name == attr and op == "ne":
            return clause.right.value
    return None


# ---------------------------------------------------------------------------
# BBox.overlaps
# ---------------------------------------------------------------------------


def test_bbox_overlaps_identical_returns_true() -> None:
    a = BBox(0, 0, 100, 100)
    b = BBox(0, 0, 100, 100)
    assert a.overlaps(b) is True


def test_bbox_overlaps_touching_no_clearance_returns_false() -> None:
    """BBox shifted by exactly w on x → edges touch but no overlap area."""
    a = BBox(0, 0, 100, 100)
    b = BBox(100, 0, 100, 100)  # touches a.right exactly
    assert a.overlaps(b) is False


def test_bbox_overlaps_with_clearance_within_gap_returns_true() -> None:
    """20 px gap < 24 px clearance → overlaps reports True."""
    a = BBox(0, 0, 100, 100)
    b = BBox(120, 0, 100, 100)  # 20 px gap on x
    assert a.overlaps(b, clearance=24) is True


# ---------------------------------------------------------------------------
# first_free_slot
# ---------------------------------------------------------------------------


def test_first_free_slot_empty_occupied_returns_seed() -> None:
    pos = first_free_slot(
        candidate_size=(192, 112),
        occupied=[],
        seed=(320, 240),
    )
    assert pos == (320, 240)


def test_first_free_slot_overlap_finds_adjacent() -> None:
    """Seed overlaps a single bbox → spiral finds an adjacent free position."""
    blocker = BBox(300, 300, 192, 112)
    pos = first_free_slot(
        candidate_size=(192, 112),
        occupied=[blocker],
        seed=(300, 300),
        clearance=0,
        step=16,
    )
    # Result must be different from the seed and must not overlap.
    assert pos != (300, 300)
    cand = BBox(pos[0], pos[1], 192, 112)
    assert not cand.overlaps(blocker)


# ---------------------------------------------------------------------------
# _compute_relatedness_seed
# ---------------------------------------------------------------------------


def test_compute_relatedness_seed_three_positions_equal_weight() -> None:
    avg = _compute_relatedness_seed([(0, 0), (300, 0), (0, 600)])
    assert avg == (100, 200)


def test_compute_relatedness_seed_empty_returns_none() -> None:
    assert _compute_relatedness_seed([]) is None


# ---------------------------------------------------------------------------
# _lane_anchor
# ---------------------------------------------------------------------------


def test_lane_anchor_top_left_returns_padding_corner() -> None:
    anchor = _lane_anchor(
        {"row": "top", "col": "left"},
        canvas_size=(2400, 1600),
        obj_size=(192, 112),
    )
    assert anchor == (LANE_PADDING, LANE_PADDING)


def test_lane_anchor_empty_returns_canvas_centre() -> None:
    canvas = (2400, 1600)
    obj = (192, 112)
    anchor = _lane_anchor({}, canvas_size=canvas, obj_size=obj)
    assert anchor == ((canvas[0] - obj[0]) // 2, (canvas[1] - obj[1]) // 2)


# ---------------------------------------------------------------------------
# incremental_place — DB-backed scenarios via FakeSession
# ---------------------------------------------------------------------------


def _make_store(
    *,
    diagram_type: DiagramType = DiagramType.SYSTEM_CONTEXT,
    placements: list[_FakePlacementRow] | None = None,
    connections: list[_FakeConnectionRow] | None = None,
    target_object_type: ObjectType = ObjectType.ACTOR,
    extra_objects: list[_FakeObjectRow] | None = None,
) -> tuple[_FakeStore, UUID, UUID]:
    diagram_id = uuid.uuid4()
    object_id = uuid.uuid4()
    store = _FakeStore(
        diagrams=[_FakeDiagramRow(id=diagram_id, type=diagram_type)],
        objects=[_FakeObjectRow(id=object_id, type=target_object_type)]
        + list(extra_objects or []),
        placements=list(placements or []),
        connections=list(connections or []),
    )
    return store, diagram_id, object_id


@pytest.mark.asyncio
async def test_incremental_place_empty_diagram_returns_lane_anchor() -> None:
    """Empty diagram, actor on context-diagram → top-left corner anchor."""
    store, diagram_id, object_id = _make_store(
        diagram_type=DiagramType.SYSTEM_CONTEXT,
        target_object_type=ObjectType.ACTOR,
    )
    db = _FakeSession(store)
    result = await incremental_place(db, diagram_id=diagram_id, object_id=object_id)
    assert isinstance(result, PlacementResult)
    assert result.w, result.h == default_size("actor")
    # Lane anchor for actor on context-diagram = (LANE_PADDING, LANE_PADDING).
    assert (result.x, result.y) == (LANE_PADDING, LANE_PADDING)


@pytest.mark.asyncio
async def test_incremental_place_existing_object_at_anchor_finds_clear_slot() -> None:
    """Same-type object already at the lane anchor → new placement does not overlap."""
    existing_object_id = uuid.uuid4()
    existing = _FakePlacementRow(
        id=uuid.uuid4(),
        diagram_id=uuid.uuid4(),  # overwritten below
        object_id=existing_object_id,
        position_x=LANE_PADDING,
        position_y=LANE_PADDING,
        width=192,
        height=112,
    )
    store, diagram_id, object_id = _make_store(
        diagram_type=DiagramType.SYSTEM_CONTEXT,
        target_object_type=ObjectType.ACTOR,
        placements=[],
        extra_objects=[_FakeObjectRow(id=existing_object_id, type=ObjectType.ACTOR)],
    )
    existing.diagram_id = diagram_id
    store.placements.append(existing)

    db = _FakeSession(store)
    result = await incremental_place(db, diagram_id=diagram_id, object_id=object_id)

    new_bbox = BBox(result.x, result.y, result.w, result.h)
    existing_bbox = BBox(
        int(existing.position_x),
        int(existing.position_y),
        int(existing.width),
        int(existing.height),
    )
    assert not new_bbox.overlaps(existing_bbox)
    # New placement should land within a handful of spiral rings of the anchor.
    # One ring = LANE_PADDING/2 (clearance) ≈ 32 px so 10 rings ≈ 320 px.
    manhattan = abs(result.x - LANE_PADDING) + abs(result.y - LANE_PADDING)
    assert manhattan <= LANE_PADDING * 10


@pytest.mark.asyncio
async def test_incremental_place_diagonal_actor_with_neighbour() -> None:
    """Actor lane is top-left.  Existing actor at (LANE_PADDING, LANE_PADDING) →
    spiral finds a non-overlapping slot for another actor."""
    existing_object_id = uuid.uuid4()
    existing = _FakePlacementRow(
        id=uuid.uuid4(),
        diagram_id=uuid.uuid4(),
        object_id=existing_object_id,
        position_x=LANE_PADDING,
        position_y=LANE_PADDING,
        width=192,
        height=112,
    )
    store, diagram_id, object_id = _make_store(
        diagram_type=DiagramType.SYSTEM_CONTEXT,
        target_object_type=ObjectType.ACTOR,
        extra_objects=[_FakeObjectRow(id=existing_object_id, type=ObjectType.ACTOR)],
    )
    existing.diagram_id = diagram_id
    store.placements.append(existing)

    db = _FakeSession(store)
    result = await incremental_place(db, diagram_id=diagram_id, object_id=object_id)
    new_bbox = BBox(result.x, result.y, result.w, result.h)
    existing_bbox = BBox(LANE_PADDING, LANE_PADDING, 192, 112)
    assert not new_bbox.overlaps(existing_bbox)


@pytest.mark.asyncio
async def test_incremental_place_relatedness_pulls_seed_toward_cluster() -> None:
    """Custom diagram (no lane hint) → seed should fall near related object."""
    related_object_id = uuid.uuid4()
    related = _FakePlacementRow(
        id=uuid.uuid4(),
        diagram_id=uuid.uuid4(),
        object_id=related_object_id,
        position_x=1000,
        position_y=500,
        width=224,
        height=128,
    )
    store, diagram_id, object_id = _make_store(
        diagram_type=DiagramType.CUSTOM,  # empty lane table → empty hint
        target_object_type=ObjectType.SYSTEM,
        extra_objects=[_FakeObjectRow(id=related_object_id, type=ObjectType.SYSTEM)],
    )
    related.diagram_id = diagram_id
    store.placements.append(related)
    store.connections.append(
        _FakeConnectionRow(
            id=uuid.uuid4(), source_id=object_id, target_id=related_object_id
        )
    )

    db = _FakeSession(store)
    result = await incremental_place(db, diagram_id=diagram_id, object_id=object_id)

    # Related-object centroid is (1000 + 112, 500 + 64) = (1112, 564); the
    # candidate (256x128) is then anchored top-left at ≈ (984, 500), which
    # overlaps the existing placement so the spiral steps out.  Allow a few
    # rings of slack — but the placement must still be in the cluster's
    # neighbourhood and must not overlap the related bbox.
    new_bbox = BBox(result.x, result.y, result.w, result.h)
    related_bbox = BBox(1000, 500, 224, 128)
    assert not new_bbox.overlaps(related_bbox)
    # The seed should pull the result toward (984, 500) — within ~10 rings.
    assert abs(result.x - 984) + abs(result.y - 500) <= LANE_PADDING * 10
