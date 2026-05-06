"""Tests for layout/lanes.py and layout/grid.py (task agent-core-mvp-052)."""

from __future__ import annotations

from app.agents.layout.grid import default_size, group_padding, snap_to_grid
from app.agents.layout.lanes import (
    LANE_TABLE,
    diagram_type_for_level,
    get_lane_hint,
)

# ---------------------------------------------------------------------------
# LANE_TABLE structure
# ---------------------------------------------------------------------------


def test_lane_table_has_four_diagram_types():
    assert set(LANE_TABLE.keys()) == {
        "context-diagram",
        "app-diagram",
        "component-diagram",
        "custom",
    }


# ---------------------------------------------------------------------------
# diagram_type_for_level
# ---------------------------------------------------------------------------


def test_diagram_type_for_level_l1_returns_context_diagram():
    assert diagram_type_for_level("L1") == "context-diagram"


def test_diagram_type_for_level_l2_returns_app_diagram():
    assert diagram_type_for_level("L2") == "app-diagram"


def test_diagram_type_for_level_l3_returns_component_diagram():
    assert diagram_type_for_level("L3") == "component-diagram"


def test_diagram_type_for_level_l4_returns_custom():
    assert diagram_type_for_level("L4") == "custom"


def test_diagram_type_for_level_unknown_returns_custom():
    assert diagram_type_for_level("L99") == "custom"


# ---------------------------------------------------------------------------
# get_lane_hint
# ---------------------------------------------------------------------------


def test_get_lane_hint_context_diagram_actor_has_row_top():
    hint = get_lane_hint("context-diagram", "actor")
    assert hint.get("row") == "top"


def test_get_lane_hint_component_diagram_app_returns_empty():
    """app objects don't belong on component diagrams — hint must be empty."""
    hint = get_lane_hint("component-diagram", "app")
    assert hint == {}


def test_get_lane_hint_returns_copy_not_reference():
    """Mutating the returned hint must not affect LANE_TABLE."""
    hint = get_lane_hint("context-diagram", "actor")
    hint["row"] = "mutated"
    assert LANE_TABLE["context-diagram"]["actor"]["row"] == "top"


def test_get_lane_hint_unknown_object_type_returns_empty():
    assert get_lane_hint("app-diagram", "totally_unknown") == {}


# ---------------------------------------------------------------------------
# snap_to_grid
# ---------------------------------------------------------------------------


def test_snap_to_grid_rounds_up_15_15():
    """15/16 = 0.9375 → rounds to 1 → 16."""
    assert snap_to_grid(15, 15) == (16, 16)


def test_snap_to_grid_ties_to_even_8_8():
    """8/16 = 0.5 — tie, rounds to nearest-even (0) → 0*16 = 0."""
    assert snap_to_grid(8, 8) == (0, 0)


def test_snap_to_grid_exact_multiple():
    assert snap_to_grid(32, 64) == (32, 64)


def test_snap_to_grid_custom_step():
    assert snap_to_grid(10, 10, step=8) == (8, 8)


# ---------------------------------------------------------------------------
# default_size
# ---------------------------------------------------------------------------


def test_default_size_actor():
    assert default_size("actor") == (192, 112)


def test_default_size_unknown_type_falls_back():
    assert default_size("unknown_type") == (224, 128)


# ---------------------------------------------------------------------------
# group_padding
# ---------------------------------------------------------------------------


def test_group_padding_returns_48():
    assert group_padding() == 48
