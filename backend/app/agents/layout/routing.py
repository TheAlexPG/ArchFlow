"""Connection routing — connector side selection + waypoint generation.

Based on IcePanel guide §8.5 / §8.7 relative-geometry table.
Output stored in connection.metadata as:
    {origin_connector, target_connector, points, line_shape, label_position}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConnectorSide = Literal[
    "top-left",
    "top-center",
    "top-right",
    "right-top",
    "right-middle",
    "right-bottom",
    "bottom-right",
    "bottom-center",
    "bottom-left",
    "left-bottom",
    "left-middle",
    "left-top",
]

LineShape = Literal["curved", "straight", "square"]

# Ratio threshold: if |dx|/|dy| > DIAGONAL_RATIO the move is considered
# primarily horizontal; if |dy|/|dx| > DIAGONAL_RATIO — primarily vertical;
# otherwise the move is diagonal.
_DIAGONAL_RATIO: float = 2.0


@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int

    @property
    def center_x(self) -> int:
        return self.x + self.w // 2

    @property
    def center_y(self) -> int:
        return self.y + self.h // 2


@dataclass
class Waypoint:
    x: int
    y: int


@dataclass
class RoutingResult:
    origin_connector: ConnectorSide
    target_connector: ConnectorSide
    points: list[Waypoint] = field(default_factory=list)
    line_shape: LineShape = "curved"
    label_position: float = 0.5  # 0..1 along the line


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pick_connector_sides(source: BBox, target: BBox) -> tuple[ConnectorSide, ConnectorSide]:
    """Per IcePanel relative-geometry table determine connector sides.

    Rules (in priority order):
    - target mostly to the right  → source=right-middle, target=left-middle
    - target mostly to the left   → source=left-middle,  target=right-middle
    - target mostly below         → source=bottom-center, target=top-center
    - target mostly above         → source=top-center,    target=bottom-center
    - diagonal top-right          → source=top-right,     target=bottom-left
    - diagonal bottom-right       → source=right-bottom,  target=left-top
    - diagonal top-left           → source=left-top,      target=right-bottom
    - diagonal bottom-left        → source=bottom-left,   target=top-right

    Tie-break: prefer side connectors over corner connectors (handled by the
    _DIAGONAL_RATIO threshold — if the horizontal or vertical displacement
    dominates, a cardinal side connector is used).
    """
    dx = target.center_x - source.center_x
    dy = target.center_y - source.center_y

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    # Avoid division by zero
    if abs_dy == 0:
        abs_dy = 1
    if abs_dx == 0:
        abs_dx = 1

    horizontal_dominant = abs_dx / abs_dy > _DIAGONAL_RATIO
    vertical_dominant = abs_dy / abs_dx > _DIAGONAL_RATIO

    if horizontal_dominant:
        # Primarily left/right movement
        if dx >= 0:
            return "right-middle", "left-middle"
        else:
            return "left-middle", "right-middle"

    if vertical_dominant:
        # Primarily up/down movement
        if dy >= 0:
            return "bottom-center", "top-center"
        else:
            return "top-center", "bottom-center"

    # Diagonal cases — use corner connectors
    if dx >= 0 and dy <= 0:
        # Target is up-right (top-right diagonal)
        return "top-right", "bottom-left"
    elif dx >= 0 and dy > 0:
        # Target is down-right (bottom-right diagonal)
        return "right-bottom", "left-top"
    elif dx < 0 and dy <= 0:
        # Target is up-left (top-left diagonal)
        return "left-top", "right-bottom"
    else:
        # Target is down-left (bottom-left diagonal)
        return "bottom-left", "top-right"


def generate_waypoints(
    source: BBox,
    target: BBox,
    *,
    obstacles: list[BBox] | None = None,
) -> list[Waypoint]:
    """Generate 0–2 intermediate waypoints for the connection.

    Phase 1 implementation:
    - No obstacles (None / empty) and line is axis-aligned: return [].
    - No obstacles and line is diagonal: return 1 midpoint waypoint.
    - Any obstacle bbox intersects the line (with clearance): return 2 waypoints
      routing around the dominant obstacle (above or below it).
    """
    src_pt = Waypoint(source.center_x, source.center_y)
    tgt_pt = Waypoint(target.center_x, target.center_y)

    # Find blocking obstacle
    blocking: BBox | None = None
    if obstacles:
        for obs in obstacles:
            if _line_intersects_bbox(src_pt, tgt_pt, obs):
                blocking = obs
                break

    if blocking is None:
        # No obstacle — check if the line is diagonal
        dx = abs(tgt_pt.x - src_pt.x)
        dy = abs(tgt_pt.y - src_pt.y)
        is_diagonal = dx > 0 and dy > 0 and not (
            dx / max(dy, 1) > _DIAGONAL_RATIO or dy / max(dx, 1) > _DIAGONAL_RATIO
        )
        if is_diagonal:
            mid = Waypoint((src_pt.x + tgt_pt.x) // 2, (src_pt.y + tgt_pt.y) // 2)
            return [mid]
        return []

    # Route around the blocking obstacle using 2 waypoints.
    # Choose whether to go above or below based on which side has more room.
    clearance = 24
    above_y = blocking.y - clearance
    below_y = blocking.y + blocking.h + clearance

    # Prefer routing above if source is above the obstacle's center, else below
    bypass_y = above_y if src_pt.y <= blocking.y + blocking.h // 2 else below_y

    wp1 = Waypoint(src_pt.x, bypass_y)
    wp2 = Waypoint(tgt_pt.x, bypass_y)
    return [wp1, wp2]


def route_connection(
    source: BBox,
    target: BBox,
    *,
    obstacles: list[BBox] | None = None,
    line_shape: LineShape = "curved",
) -> RoutingResult:
    """High-level: combine pick_connector_sides + generate_waypoints + label_position default."""
    origin_connector, target_connector = pick_connector_sides(source, target)
    points = generate_waypoints(source, target, obstacles=obstacles)
    return RoutingResult(
        origin_connector=origin_connector,
        target_connector=target_connector,
        points=points,
        line_shape=line_shape,
        label_position=0.5,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _line_intersects_bbox(p1: Waypoint, p2: Waypoint, bbox: BBox, *, clearance: int = 24) -> bool:
    """Bbox + clearance intersection check using parametric line + AABB SAT.

    Expands the bbox by *clearance* on all sides, then tests whether the
    line segment p1→p2 intersects the expanded axis-aligned bounding box.

    Uses the separating-axis theorem (SAT) for AABB vs line segment:
    a segment misses an AABB if and only if it lies entirely outside at
    least one of the four half-spaces defined by the box edges.
    """
    # Expand bbox by clearance
    ax = bbox.x - clearance
    ay = bbox.y - clearance
    bx = bbox.x + bbox.w + clearance
    by = bbox.y + bbox.h + clearance

    # Cohen–Sutherland / parametric clip (Liang–Barsky) approach.
    # We clip the segment against the four planes of the expanded AABB.
    # If t_enter <= t_exit after all clips the segment intersects.
    dx = p2.x - p1.x
    dy = p2.y - p1.y

    t_enter: float = 0.0
    t_exit: float = 1.0

    # Helper: clip against one pair of parallel planes
    # p + t*d ∈ [lo, hi]  →  t ∈ [(lo-p)/d, (hi-p)/d] (when d != 0)
    for p, d, lo, hi in (
        (p1.x, dx, ax, bx),
        (p1.y, dy, ay, by),
    ):
        if d == 0:
            # Parallel — check if the coordinate is inside the slab
            if p < lo or p > hi:
                return False
        else:
            t1 = (lo - p) / d
            t2 = (hi - p) / d
            if t1 > t2:
                t1, t2 = t2, t1
            t_enter = max(t_enter, t1)
            t_exit = min(t_exit, t2)
            if t_enter > t_exit:
                return False

    return True
