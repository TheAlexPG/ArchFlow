"""Grid + size helpers."""

from __future__ import annotations

GRID_STEP = 16
LANE_PADDING = 64

DEFAULT_SIZES: dict[str, tuple[int, int]] = {
    "actor":           (192, 112),
    "system":          (256, 128),
    "external_system": (224, 112),
    "app":             (224, 128),
    "store":           (224, 112),
    "component":       (208, 112),
    # group → fit_to_children + 48px padding (handled separately)
}

_FALLBACK_SIZE: tuple[int, int] = (224, 128)


def snap_to_grid(x: int, y: int, *, step: int = GRID_STEP) -> tuple[int, int]:
    """Returns (x, y) rounded to nearest step.

    Uses round-half-to-nearest-even (Python built-in ``round``), so ties
    round toward the nearest even multiple.  Examples:
      snap_to_grid(15, 15) → (16, 16)   — 15/16 = 0.9375, rounds to 1 → 16
      snap_to_grid(8, 8)   → (0, 0)     — 8/16 = 0.5, ties-to-even → 0 → 0
    """
    return (round(x / step) * step, round(y / step) * step)


def default_size(object_type: str) -> tuple[int, int]:
    """Default (width, height) for an object type. Falls back to (224, 128) for unknown."""
    return DEFAULT_SIZES.get(object_type, _FALLBACK_SIZE)


def group_padding() -> int:
    """Returns recommended group container padding (48)."""
    return 48
