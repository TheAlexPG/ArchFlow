"""Resolve connection handles for the agent's mutating tools.

Bridges :mod:`app.agents.layout.handles` (pure geometry) with the database:

* :func:`resolve_handles_for_connection` — given a (source, target) object
  pair, return the handle pair to record on a freshly-created connection.
  Returns ``(None, None)`` when handles can't be derived (either object
  hasn't been placed on any diagram yet, or it's placed on multiple diagrams
  with conflicting geometry — better to leave handles empty than guess).

* :func:`refresh_handles_for_object_placement` — called by ``place_on_diagram``
  after a new placement lands. Walks every connection that touches the
  freshly-placed object, fills in null handles whose other endpoint is also
  placed on the same diagram, and yields ``(connection, was_changed)`` for
  each one so the caller can fire ``connection.updated`` WS events.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agents.layout.handles import PlacementBox, auto_pick_handles

logger = logging.getLogger(__name__)


async def _get_unique_placement(
    db: Any, *, diagram_id: UUID, object_id: UUID
) -> Any | None:
    """Return the placement row for *object_id* on *diagram_id*, or None."""
    try:
        from app.services import diagram_service

        placements = await diagram_service.get_diagram_objects(db, diagram_id)
    except Exception:  # pragma: no cover — defensive
        logger.exception("get_diagram_objects failed during handle resolution")
        return None
    return next((p for p in placements if p.object_id == object_id), None)


async def _shared_diagrams(
    db: Any, *, source_id: UUID, target_id: UUID
) -> list[Any]:
    """Return diagrams where BOTH objects are placed.

    Used to find the geometry context for a fresh connection: if both
    endpoints share exactly one diagram, that diagram's placements give us
    the (source_pos, target_pos) pair the geometry helper needs.
    """
    try:
        from app.services import diagram_service

        src_diagrams = await diagram_service.get_diagrams_containing_object(
            db, source_id
        )
        tgt_diagrams = await diagram_service.get_diagrams_containing_object(
            db, target_id
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception("get_diagrams_containing_object failed")
        return []
    src_ids = {getattr(d, "id", None) for d in src_diagrams}
    return [d for d in tgt_diagrams if getattr(d, "id", None) in src_ids]


def _placement_box(placement: Any) -> PlacementBox | None:
    x = getattr(placement, "position_x", None)
    y = getattr(placement, "position_y", None)
    if x is None or y is None:
        return None
    width = getattr(placement, "width", None) or 220.0
    height = getattr(placement, "height", None) or 120.0
    try:
        return PlacementBox(
            x=float(x), y=float(y), width=float(width), height=float(height)
        )
    except (TypeError, ValueError):  # pragma: no cover — defensive
        return None


async def resolve_handles_for_connection(
    *,
    db: Any,
    source_id: UUID,
    target_id: UUID,
) -> tuple[str | None, str | None]:
    """Pick handles for a fresh connection between *source_id* and *target_id*.

    Returns ``(None, None)`` when the geometry isn't unambiguous (only one
    endpoint placed, no shared diagram, multiple shared diagrams with
    conflicting layouts, missing coordinates). The caller then records the
    connection without handles — React Flow renders a default route and the
    next ``place_on_diagram`` for either endpoint will fill in the handles
    via :func:`refresh_handles_for_object_placement`.
    """
    diagrams = await _shared_diagrams(db, source_id=source_id, target_id=target_id)
    if len(diagrams) != 1:
        # Zero shared diagrams: either endpoint not placed yet — defer.
        # Multiple shared diagrams: pick a side per-diagram instead of a
        # global one. Phase 1 leaves multi-diagram edges with empty handles
        # so each diagram's renderer falls back to the React Flow default.
        return (None, None)

    diagram_id = getattr(diagrams[0], "id", None)
    if diagram_id is None:
        return (None, None)

    src_placement = await _get_unique_placement(
        db, diagram_id=diagram_id, object_id=source_id
    )
    tgt_placement = await _get_unique_placement(
        db, diagram_id=diagram_id, object_id=target_id
    )
    if src_placement is None or tgt_placement is None:
        return (None, None)

    src_box = _placement_box(src_placement)
    tgt_box = _placement_box(tgt_placement)
    if src_box is None or tgt_box is None:
        return (None, None)

    return auto_pick_handles(src_box, tgt_box)


async def refresh_handles_for_object_placement(
    *,
    db: Any,
    diagram_id: UUID,
    object_id: UUID,
) -> list[Any]:
    """Fill in null handles on every connection that touches *object_id* on
    *diagram_id*.

    Returns a list of updated :class:`Connection` rows so the caller can
    fire ``connection.updated`` WS events for each. Connections whose
    handles are already set are left alone — explicit user choice always
    wins. Connections whose other endpoint isn't placed on *diagram_id*
    yet are also skipped (we can't compute geometry without both points).
    """
    try:
        from app.services import connection_service, object_service

        deps = await object_service.get_dependencies(db, object_id)
    except Exception:  # pragma: no cover — defensive
        logger.exception("get_dependencies failed during handle refresh")
        return []

    placements = await _all_placements(db, diagram_id=diagram_id)
    placement_by_object: dict[UUID, Any] = {p.object_id: p for p in placements}
    updated: list[Any] = []

    for conn in [*deps.get("upstream", []), *deps.get("downstream", [])]:
        if conn.source_handle and conn.target_handle:
            continue  # already has both handles, don't override
        src_id = getattr(conn, "source_id", None)
        tgt_id = getattr(conn, "target_id", None)
        if src_id is None or tgt_id is None:
            continue
        if src_id not in placement_by_object or tgt_id not in placement_by_object:
            continue  # other endpoint not on this diagram — defer
        src_box = _placement_box(placement_by_object[src_id])
        tgt_box = _placement_box(placement_by_object[tgt_id])
        if src_box is None or tgt_box is None:
            continue
        sh, th = auto_pick_handles(src_box, tgt_box)
        # Respect any partially-set handle the user (or a previous resolve)
        # already placed.
        new_source = conn.source_handle or sh
        new_target = conn.target_handle or th
        if new_source == conn.source_handle and new_target == conn.target_handle:
            continue
        try:
            from app.schemas.connection import ConnectionUpdate

            await connection_service.update_connection(
                db,
                conn,
                ConnectionUpdate(
                    source_handle=new_source,
                    target_handle=new_target,
                ),
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("update_connection failed during handle refresh")
            continue
        updated.append(conn)
    return updated


async def _all_placements(db: Any, *, diagram_id: UUID) -> list[Any]:
    try:
        from app.services import diagram_service

        return await diagram_service.get_diagram_objects(db, diagram_id)
    except Exception:  # pragma: no cover — defensive
        logger.exception("_all_placements: get_diagram_objects failed")
        return []
