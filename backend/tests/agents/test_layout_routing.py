"""Tests for connection routing — connector sides + waypoint generation.

Covers:
1.  pick_connector_sides: target right of source → (right-middle, left-middle).
2.  pick_connector_sides: target left → (left-middle, right-middle).
3.  pick_connector_sides: target below → (bottom-center, top-center).
4.  pick_connector_sides: target above → (top-center, bottom-center).
5.  pick_connector_sides: target top-right diagonal → corner combination.
6.  pick_connector_sides: target bottom-right diagonal → corner combination.
7.  generate_waypoints: clear axis-aligned path → [].
8.  generate_waypoints: diagonal clear path → 1 midpoint waypoint.
9.  generate_waypoints: obstacle in the middle → 2 waypoints.
10. _line_intersects_bbox: line through bbox → True.
11. _line_intersects_bbox: line near bbox but within clearance → True.
12. _line_intersects_bbox: line far from bbox → False.
13. route_connection happy path → valid RoutingResult with expected connectors.
"""

from __future__ import annotations

from app.agents.layout.routing import (
    BBox,
    RoutingResult,
    Waypoint,
    _line_intersects_bbox,
    generate_waypoints,
    pick_connector_sides,
    route_connection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bbox(x: int, y: int, w: int = 160, h: int = 80) -> BBox:
    """Create a BBox at (x, y) with optional size."""
    return BBox(x=x, y=y, w=w, h=h)


# ---------------------------------------------------------------------------
# pick_connector_sides
# ---------------------------------------------------------------------------


def test_pick_connector_sides_target_right() -> None:
    """Target clearly to the right → right-middle / left-middle."""
    source = _bbox(0, 200)
    target = _bbox(600, 200)  # same row, far right — strongly horizontal
    origin, dest = pick_connector_sides(source, target)
    assert origin == "right-middle"
    assert dest == "left-middle"


def test_pick_connector_sides_target_left() -> None:
    """Target clearly to the left → left-middle / right-middle."""
    source = _bbox(600, 200)
    target = _bbox(0, 200)
    origin, dest = pick_connector_sides(source, target)
    assert origin == "left-middle"
    assert dest == "right-middle"


def test_pick_connector_sides_target_below() -> None:
    """Target clearly below → bottom-center / top-center."""
    source = _bbox(300, 0)
    target = _bbox(300, 500)  # same column, far below — strongly vertical
    origin, dest = pick_connector_sides(source, target)
    assert origin == "bottom-center"
    assert dest == "top-center"


def test_pick_connector_sides_target_above() -> None:
    """Target clearly above → top-center / bottom-center."""
    source = _bbox(300, 500)
    target = _bbox(300, 0)
    origin, dest = pick_connector_sides(source, target)
    assert origin == "top-center"
    assert dest == "bottom-center"


def test_pick_connector_sides_diagonal_top_right() -> None:
    """Target diagonally up-right → source=top-right, target=bottom-left."""
    source = _bbox(0, 400)
    target = _bbox(300, 0)  # dx ≈ dy magnitude, up-right
    origin, dest = pick_connector_sides(source, target)
    assert origin == "top-right"
    assert dest == "bottom-left"


def test_pick_connector_sides_diagonal_bottom_right() -> None:
    """Target diagonally down-right → source=right-bottom, target=left-top."""
    source = _bbox(0, 0)
    target = _bbox(300, 400)  # dx ≈ dy magnitude, down-right
    origin, dest = pick_connector_sides(source, target)
    assert origin == "right-bottom"
    assert dest == "left-top"


# ---------------------------------------------------------------------------
# generate_waypoints
# ---------------------------------------------------------------------------


def test_generate_waypoints_clear_axis_aligned() -> None:
    """Purely horizontal path with no obstacles → empty waypoints list."""
    source = _bbox(0, 200)
    target = _bbox(600, 200)
    waypoints = generate_waypoints(source, target)
    assert waypoints == []


def test_generate_waypoints_clear_diagonal() -> None:
    """Diagonal path with no obstacles → single midpoint waypoint."""
    source = _bbox(0, 0)
    target = _bbox(300, 400)
    waypoints = generate_waypoints(source, target)
    assert len(waypoints) == 1
    wp = waypoints[0]
    # Midpoint between centers: (80+230)//2=155,  (40+440)//2=240
    assert isinstance(wp, Waypoint)
    src_cx = source.center_x
    tgt_cx = target.center_x
    src_cy = source.center_y
    tgt_cy = target.center_y
    assert wp.x == (src_cx + tgt_cx) // 2
    assert wp.y == (src_cy + tgt_cy) // 2


def test_generate_waypoints_obstacle_in_middle() -> None:
    """Obstacle directly between source and target → 2 bypass waypoints."""
    source = _bbox(0, 200)
    target = _bbox(600, 200)
    # Obstacle sits in the middle of the line
    obstacle = _bbox(270, 160, w=60, h=80)
    waypoints = generate_waypoints(source, target, obstacles=[obstacle])
    assert len(waypoints) == 2
    wp1, wp2 = waypoints
    assert isinstance(wp1, Waypoint)
    assert isinstance(wp2, Waypoint)
    # Both bypass waypoints must share the same bypass y-coordinate
    assert wp1.y == wp2.y
    # The bypass y must be outside the obstacle (above or below with clearance)
    clearance = 24
    obstacle_top = obstacle.y - clearance
    obstacle_bottom = obstacle.y + obstacle.h + clearance
    assert wp1.y == obstacle_top or wp1.y == obstacle_bottom


# ---------------------------------------------------------------------------
# _line_intersects_bbox
# ---------------------------------------------------------------------------


def test_line_intersects_bbox_through_center() -> None:
    """A line passing through the center of a bbox → True."""
    bbox = _bbox(100, 100, w=100, h=100)
    p1 = Waypoint(0, 150)
    p2 = Waypoint(300, 150)
    assert _line_intersects_bbox(p1, p2, bbox, clearance=0) is True


def test_line_intersects_bbox_within_clearance() -> None:
    """A line passing just outside the bbox but inside clearance → True."""
    bbox = _bbox(100, 100, w=100, h=100)
    # Line passes 10 px above the top edge (y=100); default clearance=24
    p1 = Waypoint(0, 90)
    p2 = Waypoint(300, 90)
    assert _line_intersects_bbox(p1, p2, bbox) is True


def test_line_intersects_bbox_far_away() -> None:
    """A line well outside bbox and clearance → False."""
    bbox = _bbox(100, 100, w=100, h=100)
    # Line is at y=500, far below the bbox (bottom edge at y=200, clearance=24 → 224)
    p1 = Waypoint(0, 500)
    p2 = Waypoint(300, 500)
    assert _line_intersects_bbox(p1, p2, bbox) is False


# ---------------------------------------------------------------------------
# route_connection
# ---------------------------------------------------------------------------


def test_route_connection_happy_path() -> None:
    """route_connection returns a valid RoutingResult for a straightforward pair."""
    source = _bbox(0, 200)
    target = _bbox(600, 200)
    result = route_connection(source, target)

    assert isinstance(result, RoutingResult)
    assert result.origin_connector == "right-middle"
    assert result.target_connector == "left-middle"
    assert isinstance(result.points, list)
    assert result.line_shape in ("curved", "straight", "square")
    assert 0.0 <= result.label_position <= 1.0


def test_route_connection_custom_line_shape() -> None:
    """route_connection respects the line_shape parameter."""
    source = _bbox(0, 0)
    target = _bbox(400, 0)
    result = route_connection(source, target, line_shape="straight")
    assert result.line_shape == "straight"


def test_route_connection_with_obstacle() -> None:
    """route_connection with a blocking obstacle produces 2 waypoints."""
    source = _bbox(0, 200)
    target = _bbox(600, 200)
    obstacle = _bbox(270, 160, w=60, h=80)
    result = route_connection(source, target, obstacles=[obstacle])
    assert len(result.points) == 2
