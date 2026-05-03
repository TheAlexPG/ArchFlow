"""Layout eval suite — deterministic, no LLM, no DB.

Tests the pure-function helpers from layout.engine, layout.metrics,
layout.conflict, and layout.grid with synthetic placements.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import networkx as nx
import pytest

from app.agents.layout import metrics as layout_metrics
from app.agents.layout.conflict import BBox, first_free_slot
from app.agents.layout.engine import (
    DEFAULT_CANVAS_SIZE,
    _group_by_lane,
    _topological_order_within_lane,
)
from app.agents.layout.grid import GRID_STEP, snap_to_grid
from app.agents.layout.lanes import diagram_type_for_level, get_lane_hint

GOLDEN = json.loads((Path(__file__).parent / "golden" / "layout.json").read_text())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bbox(d: dict) -> BBox:
    return BBox(x=d["x"], y=d["y"], w=d["w"], h=d["h"])


def _build_objects_with_hints(
    objects: list[dict], diagram_level: str
) -> tuple[list[UUID], dict[UUID, dict]]:
    """Create fake UUIDs + lane hints for a list of object specs."""
    diagram_type = diagram_type_for_level(diagram_level)
    ids = [uuid4() for _ in objects]
    hints: dict[UUID, dict] = {}
    for oid, obj_spec in zip(ids, objects, strict=True):
        obj_type = obj_spec["type"]
        hints[oid] = get_lane_hint(diagram_type, obj_type)
    return ids, hints


def _place_objects_no_overlap(
    ids: list[UUID],
    hints: dict[UUID, dict],
    canvas_size: tuple[int, int] = DEFAULT_CANVAS_SIZE,
) -> dict[UUID, BBox]:
    """Use _group_by_lane + snap_to_grid + first_free_slot to produce placements."""
    from app.agents.layout.grid import LANE_PADDING, default_size

    canvas_w, canvas_h = canvas_size
    groups = _group_by_lane(ids, hints)

    # Build directed graph (no connections for these tests).
    g: nx.DiGraph = nx.DiGraph()
    for oid in ids:
        g.add_node(oid)

    placements: dict[UUID, BBox] = {}
    occupied: list[BBox] = []
    row_height = canvas_h / 3.0
    lane_row_index = {"top": 0, "middle": 1, "bottom": 2, "any": 1}

    for lane_name in ("top", "middle", "bottom", "any"):
        ordered = _topological_order_within_lane(g, groups.get(lane_name, []))
        if not ordered:
            continue
        row_idx = lane_row_index.get(lane_name, 1)
        n = len(ordered)
        total_card_w = sum(
            default_size(hints.get(oid, {}).get("type", "app"))[0] for oid in ordered
        )
        usable_w = canvas_w - 2 * LANE_PADDING
        free_w = max(0, usable_w - total_card_w)
        gap = free_w // (n + 1)
        cursor_x = LANE_PADDING + gap

        for oid in ordered:
            hint = hints.get(oid, {})
            obj_type = hint.get("type", "app")
            w, h = default_size(obj_type)
            band_top = int(row_idx * row_height)
            seed_y = max(LANE_PADDING, band_top + (int(row_height) - h) // 2)
            seed_x, seed_y = snap_to_grid(cursor_x, seed_y)
            x, y = first_free_slot(
                candidate_size=(w, h),
                occupied=occupied,
                seed=(seed_x, seed_y),
                clearance=LANE_PADDING // 2,
                step=GRID_STEP,
            )
            x, y = snap_to_grid(x, y)
            bbox = BBox(x, y, w, h)
            placements[oid] = bbox
            occupied.append(bbox)
            cursor_x += w + gap

    return placements


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["id"])
def test_layout_case(case: dict) -> None:
    test_type = case["test_type"]

    if test_type == "batch_helpers":
        _run_batch_helpers_case(case)
    elif test_type == "grid_alignment":
        _run_grid_alignment_case(case)
    elif test_type == "topo_order":
        _run_topo_order_case(case)
    elif test_type == "edge_crossings":
        _run_edge_crossings_case(case)
    elif test_type == "compactness":
        _run_compactness_case(case)
    else:
        pytest.skip(f"Unknown test_type: {test_type!r}")


def _run_batch_helpers_case(case: dict) -> None:
    canvas = DEFAULT_CANVAS_SIZE
    objects = case["objects"]
    diagram_level = case.get("diagram_level", "L2")
    ids, hints = _build_objects_with_hints(objects, diagram_level)
    placements = _place_objects_no_overlap(ids, hints, canvas)

    bboxes = list(placements.values())
    overlap = layout_metrics.overlap_count(bboxes)
    assert overlap == case["expected_overlap_count"], (
        f"[{case['id']}] overlap_count={overlap}, expected {case['expected_overlap_count']}"
    )

    lane_v = layout_metrics.lane_violations(placements, hints, canvas_size=canvas)
    assert lane_v == case["expected_lane_violations"], (
        f"[{case['id']}] lane_violations={lane_v}, expected {case['expected_lane_violations']}"
    )


def _run_grid_alignment_case(case: dict) -> None:
    canvas = DEFAULT_CANVAS_SIZE
    objects = case["objects"]
    diagram_level = case.get("diagram_level", "L1")
    ids, hints = _build_objects_with_hints(objects, diagram_level)
    placements = _place_objects_no_overlap(ids, hints, canvas)
    bboxes = list(placements.values())
    violations = layout_metrics.grid_alignment_violations(bboxes, step=GRID_STEP)
    expected_v = case["expected_grid_violations"]
    assert violations == expected_v, (
        f"[{case['id']}] grid_alignment_violations={violations}, expected {expected_v}"
    )


def _run_topo_order_case(case: dict) -> None:
    n = case["num_nodes"]
    ids = [uuid4() for _ in range(n)]
    g: nx.DiGraph = nx.DiGraph()
    for oid in ids:
        g.add_node(oid)
    for src_idx, tgt_idx in case["connections"]:
        g.add_edge(ids[src_idx], ids[tgt_idx])

    ordered = _topological_order_within_lane(g, ids)
    assert len(ordered) == n, f"[{case['id']}] Expected {n} nodes in ordered, got {len(ordered)}"

    if case.get("expected_topo_ordered"):
        # Verify all connection edges respect the ordering.
        order_index = {oid: idx for idx, oid in enumerate(ordered)}
        for src_idx, tgt_idx in case["connections"]:
            src_id = ids[src_idx]
            tgt_id = ids[tgt_idx]
            assert order_index[src_id] < order_index[tgt_id], (
                f"[{case['id']}] Topo violation: {src_idx} not before {tgt_idx} in order"
            )


def _run_edge_crossings_case(case: dict) -> None:
    bboxes = [_make_bbox(b) for b in case["bboxes"]]
    edges = [(bboxes[s], bboxes[t]) for s, t in case["edges"]]
    crossings = layout_metrics.edge_crossings(edges)

    if "expected_max_crossings" in case:
        max_c = case["expected_max_crossings"]
        assert crossings <= max_c, (
            f"[{case['id']}] edge_crossings={crossings}, expected <= {max_c}"
        )
    if "expected_crossings" in case:
        exact_c = case["expected_crossings"]
        assert crossings == exact_c, (
            f"[{case['id']}] edge_crossings={crossings}, expected exactly {exact_c}"
        )


def _run_compactness_case(case: dict) -> None:
    bboxes = [_make_bbox(b) for b in case["bboxes"]]
    score = layout_metrics.compactness(bboxes)
    assert score >= case["expected_min_compactness"], (
        f"[{case['id']}] compactness={score:.3f}, expected >= {case['expected_min_compactness']}"
    )
