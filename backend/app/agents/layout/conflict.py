"""Bbox overlap + free-slot search.

Used by the layout engine (incremental_place + batch_layout) to detect
overlaps between placements and to find a non-overlapping (x, y) for a
new candidate via outward spiral search.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box (top-left origin, integer pixels)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def expanded(self, padding: int) -> BBox:
        """Return a new BBox padded by ``padding`` pixels on every side."""
        return BBox(
            self.x - padding,
            self.y - padding,
            self.w + 2 * padding,
            self.h + 2 * padding,
        )

    def overlaps(self, other: BBox, *, clearance: int = 0) -> bool:
        """True if this bbox overlaps ``other`` after expanding both by ``clearance``.

        Two AABBs are non-overlapping if either is fully to the left/right or
        fully above/below the other.  Touching edges (e.g. self.right == other.x)
        do *not* count as overlap when clearance == 0 — they share a single
        line of zero area.
        """
        a_left = self.x - clearance
        a_right = self.right + clearance
        a_top = self.y - clearance
        a_bottom = self.bottom + clearance

        if a_right <= other.x or other.right <= a_left:
            return False
        return not (a_bottom <= other.y or other.bottom <= a_top)


def first_free_slot(
    *,
    candidate_size: tuple[int, int],
    occupied: list[BBox],
    seed: tuple[int, int],
    clearance: int = 24,
    step: int = 16,
    spiral_max_rings: int = 50,
) -> tuple[int, int]:
    """Spiral search outward from seed for the first (x, y) where the
    candidate bbox does not overlap any occupied bbox plus ``clearance``.

    The seed itself is tested first.  If it is free, it is returned unchanged.
    Otherwise we walk a square spiral around the seed in rings of increasing
    radius (radius * step pixels per ring) until a free position is found or
    ``spiral_max_rings`` is exhausted.

    Returned coordinates are snapped to the grid by construction (seed +
    integer * step).  If no free slot is found within max_rings, the seed
    is returned and the caller decides whether to accept overlap.
    """
    w, h = candidate_size
    sx, sy = seed

    def _free_at(x: int, y: int) -> bool:
        cand = BBox(x, y, w, h)
        return all(not cand.overlaps(occ, clearance=clearance) for occ in occupied)

    # Try the seed first.
    if _free_at(sx, sy):
        return (sx, sy)

    # Square spiral: for each ring r in [1, spiral_max_rings], walk the
    # perimeter of a (2r+1) x (2r+1) square centred on the seed, in step-sized
    # increments.  We test every grid cell on the ring perimeter.
    for r in range(1, spiral_max_rings + 1):
        offset = r * step
        # Top edge: y = sy - offset, x from sx - offset to sx + offset (inclusive)
        # Bottom edge: y = sy + offset
        # Left/right edges (excluding corners already covered): x = sx ± offset
        # Iterate perimeter as a sequence of (dx, dy) grid offsets.
        coords: list[tuple[int, int]] = []
        # Top + bottom rows
        for k in range(-r, r + 1):
            coords.append((sx + k * step, sy - offset))
            coords.append((sx + k * step, sy + offset))
        # Left + right columns (skip corners — already added above)
        for k in range(-r + 1, r):
            coords.append((sx - offset, sy + k * step))
            coords.append((sx + offset, sy + k * step))

        for x, y in coords:
            if _free_at(x, y):
                return (x, y)

    # No free slot found within search radius — return the seed and let the
    # caller decide what to do.
    return (sx, sy)
