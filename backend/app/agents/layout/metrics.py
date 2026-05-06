"""Layout quality scores.

Used by :func:`app.agents.layout.engine.batch_layout` to attach a metrics
dict to its output, and by evals to assert correctness of the layout
engine.  Functions here are pure — they take placements (and, where
relevant, edges/lane hints) and return a numeric score.
"""

from __future__ import annotations

from itertools import combinations
from uuid import UUID

from app.agents.layout.conflict import BBox

# ---------------------------------------------------------------------------
# Per-metric helpers
# ---------------------------------------------------------------------------


def overlap_count(placements: list[BBox], *, clearance: int = 24) -> int:
    """Number of overlapping bounding-box pairs.

    Two bboxes count as overlapping if :meth:`BBox.overlaps` returns True
    after both are expanded by ``clearance`` pixels.  Identical bboxes count
    as a single overlap.  Empty / single-element lists yield 0.
    """
    if len(placements) < 2:
        return 0
    pairs = 0
    for a, b in combinations(placements, 2):
        if a.overlaps(b, clearance=clearance):
            pairs += 1
    return pairs


def edge_crossings(edges: list[tuple[BBox, BBox]]) -> int:
    """Count crossings between line segments connecting bbox centres.

    Each edge is reduced to a (centre_a, centre_b) line segment.  Two edges
    cross when the segments properly intersect — touching endpoints do not
    count.  Edges sharing a node (same source or same target bbox) are
    skipped, otherwise every fan-out would be reported as a self-cross.
    """
    if len(edges) < 2:
        return 0
    crossings = 0
    centres = [_centre_pair(e) for e in edges]
    for i, j in combinations(range(len(centres)), 2):
        a1, a2 = centres[i]
        b1, b2 = centres[j]
        # Skip edges that share a node (any endpoint is the same point).
        if a1 in (b1, b2) or a2 in (b1, b2):
            continue
        if _segments_cross(a1, a2, b1, b2):
            crossings += 1
    return crossings


def lane_violations(
    placements: dict[UUID, BBox],
    lane_hints: dict[UUID, dict],
    *,
    canvas_size: tuple[int, int],
) -> int:
    """Count bboxes whose centre lies outside their hinted lane row.

    The canvas is divided vertically into three equal bands: top / middle /
    bottom.  An object with ``row=top`` whose centre y lies in the middle
    or bottom band counts as one violation.  Objects without a row hint
    (``row=any`` or missing) are unconstrained on that axis.
    """
    if not placements:
        return 0
    _, canvas_h = canvas_size
    band = canvas_h / 3.0

    violations = 0
    for oid, bbox in placements.items():
        hint = lane_hints.get(oid) or {}
        row = hint.get("row")
        if row not in ("top", "middle", "bottom"):
            continue
        centre_y = bbox.y + bbox.h / 2.0
        actual_band = "top" if centre_y < band else (
            "middle" if centre_y < 2 * band else "bottom"
        )
        if actual_band != row:
            violations += 1
    return violations


def grid_alignment_violations(placements: list[BBox], *, step: int = 16) -> int:
    """Count placements whose top-left is not a multiple of ``step`` on both axes."""
    bad = 0
    for bbox in placements:
        if int(bbox.x) % step != 0 or int(bbox.y) % step != 0:
            bad += 1
    return bad


def compactness(placements: list[BBox]) -> float:
    """Bounding-box area density: sum(card areas) / convex bbox area.

    Returns 0.0 for empty input and for degenerate cases where the convex
    bbox has zero area.  Higher is denser.  Capped at 1.0 even though it
    is theoretically possible to exceed 1 if cards overlap heavily; for
    healthy layouts that never happens.
    """
    if not placements:
        return 0.0
    min_x = min(b.x for b in placements)
    min_y = min(b.y for b in placements)
    max_x = max(b.x + b.w for b in placements)
    max_y = max(b.y + b.h for b in placements)
    bbox_area = (max_x - min_x) * (max_y - min_y)
    if bbox_area <= 0:
        return 0.0
    used = sum(b.w * b.h for b in placements)
    return min(1.0, used / bbox_area)


def lane_balance(placements_by_lane: dict[str, list[BBox]]) -> float:
    """Population variance across lane occupancy counts.

    Returns 0.0 when one lane (or fewer) has any contents; positive numbers
    when the spread is uneven.  Lower is more balanced.
    """
    counts = [len(items) for items in placements_by_lane.values() if items]
    n = len(counts)
    if n < 2:
        return 0.0
    mean = sum(counts) / n
    variance = sum((c - mean) ** 2 for c in counts) / n
    return float(variance)


def layout_score(
    placements: list[BBox],
    connections: list[tuple[BBox, BBox]],
    placements_by_id: dict[UUID, BBox],
    canvas_size: tuple[int, int],
    *,
    hints: dict[UUID, dict] | None = None,
) -> dict:
    """Aggregate dict with all quality metrics. Used by evals + batch_layout.

    ``placements`` is the flat list of bboxes for overlap/grid/compactness;
    ``connections`` is the matching list of (src_bbox, tgt_bbox) for edge
    crossings; ``placements_by_id`` + the optional ``hints`` keyword pair
    drives the lane-violation metric.
    """
    out: dict[str, int | float] = {
        "overlap_count": overlap_count(placements),
        "edge_crossings": edge_crossings(connections),
        "grid_alignment_violations": grid_alignment_violations(placements),
        "compactness": compactness(placements),
    }
    if hints and placements_by_id:
        out["lane_violations"] = lane_violations(
            placements_by_id, hints, canvas_size=canvas_size
        )
    else:
        out["lane_violations"] = 0
    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _centre(bbox: BBox) -> tuple[float, float]:
    return (bbox.x + bbox.w / 2.0, bbox.y + bbox.h / 2.0)


def _centre_pair(edge: tuple[BBox, BBox]) -> tuple[tuple[float, float], tuple[float, float]]:
    return (_centre(edge[0]), _centre(edge[1]))


def _orient(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> int:
    """Return sign of (b-a) x (c-a): +1 / 0 / -1."""
    val = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if val > 0:
        return 1
    if val < 0:
        return -1
    return 0


def _segments_cross(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    """Proper segment intersection test (no collinear / endpoint-touching).

    Two segments p1-p2 and p3-p4 properly intersect iff the orientations
    (p1, p2, p3) and (p1, p2, p4) have opposite non-zero signs *and* the
    orientations (p3, p4, p1) and (p3, p4, p2) likewise.
    """
    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    if o1 == 0 or o2 == 0 or o3 == 0 or o4 == 0:
        return False
    return o1 != o2 and o3 != o4
