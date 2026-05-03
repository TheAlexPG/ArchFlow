"""C4 lane conventions per diagram level."""

from __future__ import annotations

from typing import Literal

DiagramLevel = Literal["L1", "L2", "L3", "L4"]
DiagramType = Literal["context-diagram", "app-diagram", "component-diagram", "custom"]


# Lane assignment per diagram type (canonical IcePanel-derived).
# Each entry: {object_type: {row, col, shape?, z?}}
LANE_TABLE: dict[DiagramType, dict[str, dict]] = {
    "context-diagram": {
        "actor":           {"row": "top",    "col": "left"},
        "system":          {"row": "middle", "col": "center"},
        "external_system": {"row": "middle", "col": "right"},
        "group":           {"shape": "area", "z": -1},
    },
    "app-diagram": {
        "app":             {"row": "middle", "col": "center"},
        "store":           {"row": "bottom", "col": "any"},
        "external_system": {"row": "any",    "col": "right"},
        "actor":           {"row": "top",    "col": "left"},
    },
    "component-diagram": {
        "component":       {"row": "middle", "col": "any"},
        "store":           {"row": "bottom", "col": "any"},
        "external_system": {"row": "any",    "col": "right"},
    },
    "custom": {},
}

_LEVEL_MAP: dict[str, DiagramType] = {
    "L1": "context-diagram",
    "L2": "app-diagram",
    "L3": "component-diagram",
}


def diagram_type_for_level(level: str) -> DiagramType:
    """Map L1→context-diagram, L2→app-diagram, L3→component-diagram, else custom."""
    return _LEVEL_MAP.get(level, "custom")


def get_lane_hint(diagram_type: DiagramType, object_type: str) -> dict:
    """Returns lane hint dict for the given (diagram_type, object_type) — empty dict if unknown."""
    return dict(LANE_TABLE.get(diagram_type, {}).get(object_type, {}))
