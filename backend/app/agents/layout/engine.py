"""Layout engine entry points: incremental_place + batch_layout (task 054).

Server-side only; the frontend renders supplied coordinates and never
computes layout itself.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.layout.conflict import BBox, first_free_slot
from app.agents.layout.grid import GRID_STEP, LANE_PADDING, default_size, snap_to_grid
from app.agents.layout.lanes import diagram_type_for_level, get_lane_hint

# Default canvas extents used when the caller does not provide one.
# 2400 x 1600 matches the IcePanel "typical workspace" guidance from §7.4.
DEFAULT_CANVAS_SIZE: tuple[int, int] = (2400, 1600)


@dataclass
class PlacementResult:
    """Result of incremental_place — a non-overlapping placement on the canvas."""

    x: int
    y: int
    w: int
    h: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def incremental_place(
    db: AsyncSession,
    *,
    diagram_id: UUID,
    object_id: UUID,
    canvas_size: tuple[int, int] = DEFAULT_CANVAS_SIZE,
) -> PlacementResult:
    """Find a non-overlapping placement for ``object_id`` on ``diagram_id``.

    Algorithm (per spec §7.4):
      1. Fetch diagram metadata (level → diagram_type via ``diagram_type_for_level``).
      2. Fetch object metadata (type → lane hint + default size).
      3. Fetch existing placements on the diagram (bbox list).
      4. Fetch connections involving this object that touch existing placements
         (relatedness scoring).
      5. Compute lane anchor based on the hint.
      6. Compute relatedness offset: weighted average position of related
         existing objects.  Combine with the lane anchor (lane priority on
         constrained axes, related-cluster centre on unconstrained ones).
      7. ``first_free_slot(seed)`` → (x, y).
      8. Snap to grid; return PlacementResult.
    """
    # Local imports keep import cost low for callers that only need helpers.
    from app.models.connection import Connection
    from app.models.diagram import Diagram, DiagramObject
    from app.models.object import ModelObject

    # 1. Diagram metadata → lane diagram_type
    diagram = (await db.execute(select(Diagram).where(Diagram.id == diagram_id))).scalar_one()
    level = _level_for_diagram_type(diagram.type)
    lane_diagram_type = diagram_type_for_level(level)

    # 2. Object metadata → lane hint + default size
    obj = (await db.execute(select(ModelObject).where(ModelObject.id == object_id))).scalar_one()
    obj_type = obj.type.value if hasattr(obj.type, "value") else str(obj.type)
    hint = get_lane_hint(lane_diagram_type, obj_type)
    obj_size = default_size(obj_type)

    # 3. Existing placements on this diagram (excluding the target object — if
    #    it is already placed we still want to recompute against the others).
    placements_rows = (
        await db.execute(
            select(DiagramObject).where(
                DiagramObject.diagram_id == diagram_id,
                DiagramObject.object_id != object_id,
            )
        )
    ).scalars().all()

    occupied: list[BBox] = []
    placement_by_object: dict[UUID, BBox] = {}
    for row in placements_rows:
        w = int(row.width) if row.width is not None else default_size("unknown")[0]
        h = int(row.height) if row.height is not None else default_size("unknown")[1]
        bbox = BBox(int(row.position_x), int(row.position_y), w, h)
        occupied.append(bbox)
        placement_by_object[row.object_id] = bbox

    # 4. Relatedness — connections touching this object whose other endpoint
    #    is already placed on this diagram.
    related_positions: list[tuple[int, int]] = []
    related_weights: list[float] = []
    if placement_by_object:
        connections = (
            await db.execute(
                select(Connection).where(
                    (Connection.source_id == object_id) | (Connection.target_id == object_id)
                )
            )
        ).scalars().all()
        connection_counts: dict[UUID, int] = {}
        for conn in connections:
            other_id = conn.target_id if conn.source_id == object_id else conn.source_id
            if other_id in placement_by_object:
                connection_counts[other_id] = connection_counts.get(other_id, 0) + 1
        for other_id, count in connection_counts.items():
            other_bbox = placement_by_object[other_id]
            related_positions.append(
                (other_bbox.x + other_bbox.w // 2, other_bbox.y + other_bbox.h // 2)
            )
            related_weights.append(float(count))

    # 5–6. Compute seed: blend lane anchor with relatedness centre.
    lane_anchor = _lane_anchor(hint, canvas_size=canvas_size, obj_size=obj_size)
    related_centre = _compute_relatedness_seed(related_positions, weights=related_weights)
    seed = _combine_seed(
        lane_anchor=lane_anchor,
        related_centre=related_centre,
        hint=hint,
        obj_size=obj_size,
    )
    seed = snap_to_grid(*seed)

    # 7. Spiral search for the first free slot.
    x, y = first_free_slot(
        candidate_size=obj_size,
        occupied=occupied,
        seed=seed,
        clearance=LANE_PADDING // 2,
        step=GRID_STEP,
    )

    # 8. Final snap (defensive — first_free_slot already returns grid-aligned
    #    coordinates relative to a grid-aligned seed).
    x, y = snap_to_grid(x, y)
    return PlacementResult(x=x, y=y, w=obj_size[0], h=obj_size[1])


# ---------------------------------------------------------------------------
# Helpers (exposed for unit tests)
# ---------------------------------------------------------------------------


def _compute_relatedness_seed(
    related_positions: list[tuple[int, int]],
    *,
    weights: list[float] | None = None,
) -> tuple[int, int] | None:
    """Weighted average of ``related_positions``.  Returns None if empty.

    Weights default to 1.0 each.  Zero-or-negative total weight collapses to
    a plain arithmetic mean.
    """
    if not related_positions:
        return None
    if weights is None:
        weights = [1.0] * len(related_positions)
    if len(weights) != len(related_positions):
        raise ValueError("weights length must match related_positions length")

    total_w = sum(weights)
    if total_w <= 0:
        # Fall back to a uniform mean.
        weights = [1.0] * len(related_positions)
        total_w = float(len(related_positions))

    sx = sum(p[0] * w for p, w in zip(related_positions, weights, strict=True)) / total_w
    sy = sum(p[1] * w for p, w in zip(related_positions, weights, strict=True)) / total_w
    return (int(round(sx)), int(round(sy)))


def _lane_anchor(
    hint: dict,
    *,
    canvas_size: tuple[int, int],
    obj_size: tuple[int, int],
) -> tuple[int, int]:
    """Map a lane hint to an (x, y) anchor on the canvas.

    Coordinate map (origin top-left, growing right/down):
      row=top    → y = LANE_PADDING
      row=middle → y = (canvas_h - obj_h) / 2
      row=bottom → y = canvas_h - obj_h - LANE_PADDING
      col=left   → x = LANE_PADDING
      col=center → x = (canvas_w - obj_w) / 2
      col=right  → x = canvas_w - obj_w - LANE_PADDING

    row=any/missing or col=any/missing → that axis falls back to canvas
    centre on the corresponding axis.  An entirely empty hint therefore
    anchors to the canvas centre.
    """
    canvas_w, canvas_h = canvas_size
    obj_w, obj_h = obj_size

    row = hint.get("row")
    col = hint.get("col")

    if row == "top":
        y = LANE_PADDING
    elif row == "bottom":
        y = canvas_h - obj_h - LANE_PADDING
    else:  # "middle", "any", or missing
        y = (canvas_h - obj_h) // 2

    if col == "left":
        x = LANE_PADDING
    elif col == "right":
        x = canvas_w - obj_w - LANE_PADDING
    else:  # "center", "any", or missing
        x = (canvas_w - obj_w) // 2

    return (x, y)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _combine_seed(
    *,
    lane_anchor: tuple[int, int],
    related_centre: tuple[int, int] | None,
    hint: dict,
    obj_size: tuple[int, int],
) -> tuple[int, int]:
    """Blend lane anchor with related-cluster centre.

    Lane has priority on axes where the hint is constrained
    (row in {top, middle, bottom} or col in {left, center, right}).  On
    unconstrained axes (row/col == "any" or missing) we use the
    related-cluster coordinate when one exists.
    """
    if related_centre is None:
        return lane_anchor

    row = hint.get("row")
    col = hint.get("col")
    obj_w, obj_h = obj_size

    row_constrained = row in {"top", "middle", "bottom"}
    col_constrained = col in {"left", "center", "right"}

    # Related centre is given as a centroid; convert to top-left.
    rel_x = related_centre[0] - obj_w // 2
    rel_y = related_centre[1] - obj_h // 2

    x = lane_anchor[0] if col_constrained else rel_x
    y = lane_anchor[1] if row_constrained else rel_y
    return (x, y)


# Map ORM ``DiagramType`` enum values back to a C4 level so we can reuse the
# lane table.  Mirrors ``app/agents/tools/model_tools.py``'s level filter.
_DIAGRAM_TYPE_TO_LEVEL: dict[str, str] = {
    "system_landscape": "L1",
    "system_context": "L1",
    "container": "L2",
    "component": "L3",
    "custom": "L4",
}


def _level_for_diagram_type(diagram_type: object) -> str:
    """Return ``L1`` / ``L2`` / ``L3`` / ``L4`` for a Diagram.type value."""
    raw = diagram_type.value if hasattr(diagram_type, "value") else str(diagram_type)
    return _DIAGRAM_TYPE_TO_LEVEL.get(raw, "L4")


# ---------------------------------------------------------------------------
# Batch layout (Sugiyama-flavoured multipartite layout)
# ---------------------------------------------------------------------------


# Lane row → multipartite "subset" partition index. Top of canvas is row 0.
_LANE_ROW_INDEX: dict[str, int] = {"top": 0, "middle": 1, "bottom": 2, "any": 1}


@dataclass
class BatchLayoutPlan:
    """Result of :func:`batch_layout`.

    ``moves`` is the (possibly empty) ordered list of repositionings the caller
    should apply: ``(object_id, x, y)``.  ``placements_full`` is the entire
    layout — including objects that did not move — keyed by object id.  It is
    handy for tests and for serializing previews.  ``metrics`` carries the
    quality-score dict produced by :mod:`app.agents.layout.metrics`.
    """

    moves: list[tuple[UUID, int, int]] = field(default_factory=list)
    placements_full: dict[UUID, PlacementResult] = field(default_factory=dict)
    metrics: dict[str, int | float] = field(default_factory=dict)


async def batch_layout(
    db: AsyncSession,
    *,
    diagram_id: UUID,
    scope: Literal["new_only", "all"] = "new_only",
    canvas_size: tuple[int, int] = DEFAULT_CANVAS_SIZE,
) -> BatchLayoutPlan:
    """Layered + lane-aware Sugiyama via :func:`networkx.multipartite_layout`.

    Steps:
      1. Fetch diagram, level → diagram_type.
      2. Fetch placements + the model objects they reference + the connections
         that touch any of those objects.
      3. Build a directed graph from connections (direction='outgoing').
      4. Group objects into lane rows (top/middle/bottom) per spec lane hints.
      5. Topologically sort within each lane.
      6. Compute (x, y) positions:
           - row anchor:   ``lane_y_index * canvas_h / 3 + LANE_PADDING``
           - within-row x: spread evenly with ``LANE_PADDING`` separation
           - new_only:     preserve x/y of objects that already have positions
           - all:          replace every position
      7. Snap to grid; resolve any residual overlaps with
         :func:`first_free_slot`.
      8. Return a :class:`BatchLayoutPlan` with ``moves`` (changed ids),
         ``placements_full`` (every id), and ``metrics``.
    """
    from app.agents.layout import metrics as layout_metrics
    from app.models.connection import Connection
    from app.models.diagram import Diagram, DiagramObject
    from app.models.object import ModelObject

    # 1. Diagram metadata.
    diagram = (
        await db.execute(select(Diagram).where(Diagram.id == diagram_id))
    ).scalar_one()
    level = _level_for_diagram_type(diagram.type)
    lane_diagram_type = diagram_type_for_level(level)

    # 2. Placements + objects + connections.
    placement_rows = (
        await db.execute(
            select(DiagramObject).where(DiagramObject.diagram_id == diagram_id)
        )
    ).scalars().all()

    if not placement_rows:
        return BatchLayoutPlan(
            moves=[],
            placements_full={},
            metrics=layout_metrics.layout_score([], [], {}, canvas_size),
        )

    object_ids = [row.object_id for row in placement_rows]

    object_rows = (
        await db.execute(
            select(ModelObject).where(ModelObject.id.in_(object_ids))
        )
    ).scalars().all()
    obj_by_id: dict[UUID, ModelObject] = {row.id: row for row in object_rows}

    # Connections where both endpoints are placed on this diagram.
    connection_rows = (
        await db.execute(
            select(Connection).where(
                Connection.source_id.in_(object_ids),
                Connection.target_id.in_(object_ids),
            )
        )
    ).scalars().all()

    # Per-object lane hint, default size, and starting bbox.
    lane_hints: dict[UUID, dict] = {}
    object_sizes: dict[UUID, tuple[int, int]] = {}
    existing_positions: dict[UUID, tuple[int, int]] = {}

    for row in placement_rows:
        obj = obj_by_id.get(row.object_id)
        obj_type = (
            (obj.type.value if hasattr(obj.type, "value") else str(obj.type))
            if obj is not None
            else "unknown"
        )
        hint = get_lane_hint(lane_diagram_type, obj_type) if obj is not None else {}
        lane_hints[row.object_id] = hint
        w_default, h_default = default_size(obj_type)
        w = int(row.width) if row.width is not None else w_default
        h = int(row.height) if row.height is not None else h_default
        object_sizes[row.object_id] = (w, h)
        if row.position_x is not None and row.position_y is not None:
            x_int = int(row.position_x)
            y_int = int(row.position_y)
            existing_positions[row.object_id] = (x_int, y_int)

    # 3. Build the directed graph for topological hints.
    graph: nx.DiGraph = nx.DiGraph()
    for oid in object_ids:
        graph.add_node(oid)
    for conn in connection_rows:
        # Treat unidirectional and bidirectional as forward edges; undirected
        # connections still influence the order, but as a soft hint.
        graph.add_edge(conn.source_id, conn.target_id)

    # 4-5. Lane assignment + topo order within each lane.
    lane_groups = _group_by_lane(object_ids, lane_hints)
    ordered_by_lane: dict[str, list[UUID]] = {}
    for lane_name, lane_objs in lane_groups.items():
        ordered_by_lane[lane_name] = _topological_order_within_lane(graph, lane_objs)

    # 6. Position calculation.
    canvas_w, canvas_h = canvas_size
    row_height = canvas_h / 3.0

    def _row_anchor_y(row_idx: int, obj_h: int) -> int:
        # Center the object vertically within its row band; clamp to LANE_PADDING.
        band_top = int(row_idx * row_height)
        anchor = band_top + (int(row_height) - obj_h) // 2
        return max(LANE_PADDING, anchor)

    placements_full: dict[UUID, PlacementResult] = {}
    moves: list[tuple[UUID, int, int]] = []
    occupied: list[BBox] = []

    # When scope='new_only' we keep existing positions verbatim and only place
    # the rest.  Pre-seed `placements_full` and `occupied` with those rows.
    if scope == "new_only":
        for oid, (ex_x, ex_y) in existing_positions.items():
            w, h = object_sizes[oid]
            placements_full[oid] = PlacementResult(x=ex_x, y=ex_y, w=w, h=h)
            occupied.append(BBox(ex_x, ex_y, w, h))

    # Walk lanes top → bottom for stable, deterministic results.
    for lane_name in ("top", "middle", "bottom", "any"):
        ordered = ordered_by_lane.get(lane_name, [])
        if not ordered:
            continue
        if scope == "new_only":
            ordered = [oid for oid in ordered if oid not in placements_full]
        if not ordered:
            continue

        row_idx = _LANE_ROW_INDEX.get(lane_name, 1)

        # Spread x evenly across the canvas inside the row, leaving a
        # LANE_PADDING margin on either side and between cards.
        n = len(ordered)
        usable_w = max(1, canvas_w - 2 * LANE_PADDING)
        total_card_w = sum(object_sizes[oid][0] for oid in ordered)
        free_w = max(0, usable_w - total_card_w)
        gap = free_w // (n + 1) if n > 0 else 0

        cursor_x = LANE_PADDING + gap
        for oid in ordered:
            w, h = object_sizes[oid]
            seed_x, seed_y = snap_to_grid(cursor_x, _row_anchor_y(row_idx, h))

            x, y = first_free_slot(
                candidate_size=(w, h),
                occupied=occupied,
                seed=(seed_x, seed_y),
                clearance=LANE_PADDING // 2,
                step=GRID_STEP,
            )
            x, y = snap_to_grid(x, y)

            placements_full[oid] = PlacementResult(x=x, y=y, w=w, h=h)
            occupied.append(BBox(x, y, w, h))

            ex = existing_positions.get(oid)
            if ex is None or ex != (x, y):
                moves.append((oid, x, y))

            cursor_x += w + gap

    # 7-8. Metrics.
    placement_bboxes = [
        BBox(p.x, p.y, p.w, p.h) for p in placements_full.values()
    ]
    edges_for_metrics: list[tuple[BBox, BBox]] = []
    for conn in connection_rows:
        src = placements_full.get(conn.source_id)
        tgt = placements_full.get(conn.target_id)
        if src is None or tgt is None:
            continue
        edges_for_metrics.append(
            (BBox(src.x, src.y, src.w, src.h), BBox(tgt.x, tgt.y, tgt.w, tgt.h))
        )

    bbox_by_id: dict[UUID, BBox] = {
        oid: BBox(p.x, p.y, p.w, p.h) for oid, p in placements_full.items()
    }

    metrics = layout_metrics.layout_score(
        placement_bboxes,
        edges_for_metrics,
        bbox_by_id,
        canvas_size,
        hints=lane_hints,
    )

    return BatchLayoutPlan(
        moves=moves, placements_full=placements_full, metrics=metrics
    )


# ---------------------------------------------------------------------------
# Batch helpers (exposed for unit tests)
# ---------------------------------------------------------------------------


def _group_by_lane(
    object_ids: list[UUID], hints: dict[UUID, dict]
) -> dict[str, list[UUID]]:
    """Group object ids into lane rows: top / middle / bottom / any.

    Objects whose hint has ``row=any`` (or no row at all) are routed to the
    "middle" bucket — that matches the canonical IcePanel spread.
    """
    groups: dict[str, list[UUID]] = defaultdict(list)
    for oid in object_ids:
        hint = hints.get(oid) or {}
        row = hint.get("row") or "middle"
        if row == "any":
            row = "middle"
        if row not in ("top", "middle", "bottom"):
            row = "middle"
        groups[row].append(oid)
    return dict(groups)


def _topological_order_within_lane(
    graph: nx.DiGraph, lane_objects: list[UUID]
) -> list[UUID]:
    """Topologically sort ``lane_objects`` using edges from ``graph``.

    The sort respects edge ordering inside the lane only — edges that point
    out of the lane are ignored.  Among nodes that share the same
    topological rank, the original input ordering is preserved
    (stable / deterministic).  If the induced subgraph contains a cycle
    we fall back to the input order.
    """
    if not lane_objects:
        return []
    sub = graph.subgraph(lane_objects).copy()
    rank = {oid: idx for idx, oid in enumerate(lane_objects)}
    try:
        ordered = list(nx.lexicographical_topological_sort(sub, key=rank.get))
    except nx.NetworkXUnfeasible:
        return list(lane_objects)
    return ordered
