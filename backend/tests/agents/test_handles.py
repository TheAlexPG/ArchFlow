"""Unit tests for the auto-pick handles helper.

Geometry only — no DB, no schema, no network. The resolver / refresh
integration is covered separately via the diagram tool tests.
"""

from __future__ import annotations

from app.agents.layout.handles import (
    PlacementBox,
    auto_pick_handles,
    is_valid_handle,
)


def test_horizontal_route_right_to_left():
    src = PlacementBox(x=0, y=200)
    tgt = PlacementBox(x=400, y=210)  # mostly to the right
    assert auto_pick_handles(src, tgt) == ("right", "left")


def test_horizontal_route_left_to_right():
    src = PlacementBox(x=400, y=200)
    tgt = PlacementBox(x=0, y=210)  # mostly to the left
    assert auto_pick_handles(src, tgt) == ("left", "right")


def test_vertical_route_bottom_to_top():
    src = PlacementBox(x=200, y=0)
    tgt = PlacementBox(x=210, y=400)  # mostly below
    assert auto_pick_handles(src, tgt) == ("bottom", "top")


def test_vertical_route_top_to_bottom():
    src = PlacementBox(x=200, y=400)
    tgt = PlacementBox(x=210, y=0)  # mostly above
    assert auto_pick_handles(src, tgt) == ("top", "bottom")


def test_tie_breaks_horizontal():
    """When |Δx| == |Δy| we prefer horizontal — most C4 diagrams flow
    left→right and horizontal handles read better."""
    src = PlacementBox(x=0, y=0)
    tgt = PlacementBox(x=300, y=300)
    sh, th = auto_pick_handles(src, tgt)
    assert sh in ("right", "left") and th in ("right", "left")


def test_overlapping_centres_returns_a_pair():
    """Same centre — algorithm must still return a valid handle pair (not
    raise). Either horizontal or vertical is acceptable."""
    src = PlacementBox(x=0, y=0)
    tgt = PlacementBox(x=0, y=0)
    sh, th = auto_pick_handles(src, tgt)
    assert is_valid_handle(sh)
    assert is_valid_handle(th)


def test_is_valid_handle():
    assert is_valid_handle("top")
    assert is_valid_handle("right")
    assert is_valid_handle("bottom")
    assert is_valid_handle("left")
    assert not is_valid_handle("center")
    assert not is_valid_handle(None)
    assert not is_valid_handle("")
    assert not is_valid_handle("TOP")  # case-sensitive on purpose
