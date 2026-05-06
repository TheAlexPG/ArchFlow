"""Realtime broadcast helpers for agent mutating tools.

Mirrors the publish behaviour of the REST endpoints in ``app/api/v1/`` so live
canvas / workspace clients see agent-driven mutations the moment a tool fires
— without waiting for the SSE stream to flush ``applied_change`` events back
to the chat client (which then has to ``invalidateQueries`` and refetch).

The frontend's ``useWorkspaceSocket`` / ``useDiagramSocket`` consume the
payloads directly (``setQueriesData(..., mergeEntity(prev, body))``) so we
match the REST payload shape exactly: ``{"object": ...}``, ``{"connection":
...}``, ``{"diagram_id": ..., "diagram_object": ...}`` etc.

Skips when ``draft_id`` is set — REST does the same; draft mutations stay
private to the draft owner until merged.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from app.realtime.manager import (
    fire_and_forget_publish,
    fire_and_forget_publish_diagram,
)
from app.services.webhook_service import fire_and_forget_emit

logger = logging.getLogger(__name__)


def _safe_uuid(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


async def _diagrams_containing(db: Any, object_id: UUID) -> list[Any]:
    try:
        from app.services import diagram_service

        return await diagram_service.get_diagrams_containing_object(db, object_id)
    except Exception:  # pragma: no cover — defensive
        logger.exception("realtime fanout: get_diagrams_containing_object failed")
        return []


def publish_object_event(
    *,
    obj: Any,
    event_type: str,
    draft_id: Any | None = None,
) -> None:
    """Publish ``object.created`` / ``object.updated`` / ``object.deleted``.

    For ``object.deleted`` the caller passes a stub with ``id`` only; we ship
    ``{"id": "..."}`` instead of the full body so the WS subscriber removes
    the row from its cache. Otherwise we publish the full ``ObjectResponse``.
    """
    if draft_id is not None:
        return
    workspace_id = _safe_uuid(getattr(obj, "workspace_id", None))
    obj_id = _safe_uuid(getattr(obj, "id", None))

    if event_type == "object.deleted":
        if obj_id is None:
            return
        payload = {"id": str(obj_id)}
        fire_and_forget_emit(event_type, payload)
        fire_and_forget_publish(workspace_id, event_type, payload)
        return

    try:
        from app.schemas.object import ObjectResponse

        body = ObjectResponse.from_model(obj).model_dump(mode="json")
    except Exception:  # pragma: no cover — defensive
        logger.exception("publish_object_event: ObjectResponse.from_model failed")
        return

    fire_and_forget_emit(event_type, body)
    fire_and_forget_publish(workspace_id, event_type, {"object": body})


async def publish_object_event_with_diagram_fanout(
    *,
    db: Any,
    obj: Any,
    event_type: str,
    draft_id: Any | None = None,
) -> None:
    """Same as :func:`publish_object_event` plus fanout to every diagram
    containing the object — needed for ``object.updated`` / ``object.deleted``
    so open canvases re-render the affected node."""
    publish_object_event(obj=obj, event_type=event_type, draft_id=draft_id)
    if draft_id is not None:
        return
    obj_id = _safe_uuid(getattr(obj, "id", None))
    if obj_id is None:
        return
    diagrams = await _diagrams_containing(db, obj_id)
    if event_type == "object.deleted":
        payload: dict[str, Any] = {"id": str(obj_id)}
    else:
        try:
            from app.schemas.object import ObjectResponse

            body = ObjectResponse.from_model(obj).model_dump(mode="json")
        except Exception:  # pragma: no cover — defensive
            logger.exception("fanout payload build failed")
            return
        payload = {"object": body}
    for d in diagrams:
        fire_and_forget_publish_diagram(getattr(d, "id", None), event_type, payload)


async def publish_connection_event(
    *,
    db: Any,
    conn: Any,
    event_type: str,
    draft_id: Any | None = None,
) -> None:
    """Publish ``connection.created/updated/deleted`` to workspace + endpoint
    diagrams. Mirrors :mod:`app/api/v1/connections.py`."""
    if draft_id is not None or getattr(conn, "draft_id", None) is not None:
        return

    src_id = _safe_uuid(getattr(conn, "source_id", None))
    tgt_id = _safe_uuid(getattr(conn, "target_id", None))
    conn_id = _safe_uuid(getattr(conn, "id", None))

    if event_type == "connection.deleted":
        if conn_id is None:
            return
        payload: dict[str, Any] = {"id": str(conn_id)}
        # Workspace publish — derive workspace_id from source object lookup.
        workspace_id = await _workspace_for_object(db, src_id)
        fire_and_forget_emit(event_type, payload)
        fire_and_forget_publish(workspace_id, event_type, payload)
        await _fanout_to_endpoint_diagrams(
            db, src_id, tgt_id, event_type, payload
        )
        return

    try:
        from app.schemas.connection import ConnectionResponse

        body = ConnectionResponse.model_validate(conn).model_dump(mode="json")
    except Exception:  # pragma: no cover — defensive
        logger.exception("publish_connection_event: ConnectionResponse.model_validate failed")
        return

    workspace_id = await _workspace_for_object(db, src_id)
    fire_and_forget_emit(event_type, body)
    fire_and_forget_publish(workspace_id, event_type, {"connection": body})
    await _fanout_to_endpoint_diagrams(
        db, src_id, tgt_id, event_type, {"connection": body}
    )


async def _workspace_for_object(db: Any, object_id: UUID | None) -> UUID | None:
    if object_id is None:
        return None
    try:
        from app.services import object_service

        obj = await object_service.get_object(db, object_id)
        return _safe_uuid(getattr(obj, "workspace_id", None)) if obj else None
    except Exception:  # pragma: no cover — defensive
        logger.exception("_workspace_for_object failed")
        return None


async def _fanout_to_endpoint_diagrams(
    db: Any,
    source_id: UUID | None,
    target_id: UUID | None,
    event_type: str,
    payload: dict,
) -> None:
    seen: set[uuid.UUID] = set()
    for endpoint in (source_id, target_id):
        if endpoint is None:
            continue
        for d in await _diagrams_containing(db, endpoint):
            d_id = getattr(d, "id", None)
            if d_id in seen:
                continue
            seen.add(d_id)
            fire_and_forget_publish_diagram(d_id, event_type, payload)


def publish_diagram_event(
    *,
    diagram: Any,
    event_type: str,
    draft_id: Any | None = None,
) -> None:
    """Publish ``diagram.created/updated/deleted`` to the workspace channel.
    Mirrors :mod:`app/api/v1/diagrams.py`."""
    if draft_id is not None or getattr(diagram, "draft_id", None) is not None:
        return
    workspace_id = _safe_uuid(getattr(diagram, "workspace_id", None))
    diagram_id = _safe_uuid(getattr(diagram, "id", None))

    if event_type == "diagram.deleted":
        if diagram_id is None:
            return
        fire_and_forget_publish(workspace_id, event_type, {"id": str(diagram_id)})
        return

    try:
        from app.schemas.diagram import DiagramResponse

        body = DiagramResponse.model_validate(diagram).model_dump(mode="json")
    except Exception:  # pragma: no cover — defensive
        logger.exception("publish_diagram_event: DiagramResponse.model_validate failed")
        return
    fire_and_forget_publish(workspace_id, event_type, {"diagram": body})


async def publish_placement_event(
    *,
    db: Any,
    diagram_id: UUID,
    placement: Any,
    event_type: str,
    object_id: UUID | None = None,
    draft_id: Any | None = None,
) -> None:
    """Publish ``diagram_object.added/updated/removed``.

    For ``added``/``updated`` the placement row carries x/y/w/h.  For
    ``removed`` we ship ``{diagram_id, object_id}`` so the FE drops the row
    from its cache.
    """
    if draft_id is not None:
        return

    try:
        from app.services import diagram_service

        diagram = await diagram_service.get_diagram(db, diagram_id)
    except Exception:  # pragma: no cover — defensive
        diagram = None
    workspace_id = _safe_uuid(getattr(diagram, "workspace_id", None)) if diagram else None

    if event_type == "diagram_object.removed":
        oid = object_id or _safe_uuid(getattr(placement, "object_id", None))
        if oid is None:
            return
        payload = {"diagram_id": str(diagram_id), "object_id": str(oid)}
        fire_and_forget_publish(workspace_id, event_type, payload)
        fire_and_forget_publish_diagram(diagram_id, event_type, payload)
        return

    try:
        from app.schemas.diagram import DiagramObjectResponse

        body = DiagramObjectResponse.model_validate(placement).model_dump(mode="json")
    except Exception:  # pragma: no cover — defensive
        logger.exception("publish_placement_event: DiagramObjectResponse failed")
        return
    payload = {"diagram_id": str(diagram_id), "diagram_object": body}
    fire_and_forget_publish(workspace_id, event_type, payload)
    fire_and_forget_publish_diagram(diagram_id, event_type, payload)
