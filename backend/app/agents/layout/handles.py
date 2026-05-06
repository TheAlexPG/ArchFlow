"""Auto-pick connection handles based on placement geometry.

When the agent creates an edge between two placed objects we pick the most
visually sensible side of each node for the line endpoint:

  * ``Δx`` dominates → horizontal route → ``right`` ↔ ``left``.
  * ``Δy`` dominates (or ties) → vertical route → ``bottom`` ↔ ``top``.

Without this, React Flow falls back to the default handle (``top``) and
edges criss-cross over node bodies — visually noisy, semantically wrong
("right-of" relationships rendered as overhead lines).

The helper is geometry-only — it takes the two placement rectangles and
returns the handle pair. It does not touch DB rows.

The agent can also pass explicit ``source_handle`` / ``target_handle`` via
the ``create_connection`` tool (one or both); the auto-pick path only fills
in handles the caller left as ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass


# React Flow handle ids declared on every node (`C4Node`, `ActorNode`,
# `ExternalSystemNode`, `GroupNode`).  Keep this list in sync with the
# ``<Handle id="...">`` declarations on the FE side.
VALID_HANDLES: frozenset[str] = frozenset({"top", "right", "bottom", "left"})


@dataclass(frozen=True)
class PlacementBox:
    """A placement rectangle in canvas coordinates.

    ``x`` / ``y`` are the **top-left** corner of the node (matches how the FE
    canvas stores positions). Width/height default to the standard node size
    used by the layout grid.
    """

    x: float
    y: float
    width: float = 220.0
    height: float = 120.0

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


def auto_pick_handles(source: PlacementBox, target: PlacementBox) -> tuple[str, str]:
    """Return ``(source_handle, target_handle)`` for an edge between *source*
    and *target*.

    Algorithm:
      * If the horizontal gap dominates (``|Δx| >= |Δy|``) the edge is a
        horizontal route — exit *source* on the side facing *target*, enter
        *target* on the opposite side.
      * Otherwise the edge is vertical: exit/enter via top/bottom.

    The "≥" tie-breaker biases toward horizontal handles, which is what most
    C4 architecture diagrams want (left-to-right flow). If you ever need
    vertical bias for a specific diagram type, push the choice up to a caller
    and pass the strategy in.
    """
    dx = target.cx - source.cx
    dy = target.cy - source.cy

    if abs(dx) >= abs(dy):
        if dx >= 0:
            return ("right", "left")
        return ("left", "right")

    if dy >= 0:
        return ("bottom", "top")
    return ("top", "bottom")


def is_valid_handle(value: str | None) -> bool:
    """Return True iff *value* names one of the four declared FE handles."""
    return value in VALID_HANDLES
