import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.connection import Connection
from app.models.diagram import Diagram, DiagramObject
from app.models.object import ModelObject
from app.models.technology import Technology
from app.schemas.diagram import (
    DiagramCreate,
    DiagramObjectCreate,
    DiagramObjectUpdate,
    DiagramUpdate,
)
from app.services import activity_service


async def get_diagram_payload(
    db: AsyncSession, diagram: Diagram
) -> dict:
    """Load every row needed to render or export a diagram in one place.

    Returns:
        placements: DiagramObjects on this diagram, with `.object` eager-loaded.
        connections: Connections where both endpoints are placed on this diagram.
        tech_names: id → display name for every technology referenced by an
            object's technology_ids or a connection's protocol_ids.
    """
    placements_q = (
        select(DiagramObject)
        .where(DiagramObject.diagram_id == diagram.id)
        .options(selectinload(DiagramObject.object))
    )
    placements = list((await db.execute(placements_q)).scalars().all())

    object_ids = [p.object_id for p in placements]
    if not object_ids:
        return {"placements": [], "connections": [], "tech_names": {}}

    # Scope connections by the diagram's draft context so a forked diagram's
    # in-progress edges never leak into a live export, and vice versa. Mirrors
    # connection_service.get_connections().
    conn_q = select(Connection).where(
        Connection.source_id.in_(object_ids),
        Connection.target_id.in_(object_ids),
    )
    if diagram.draft_id is None:
        conn_q = conn_q.where(Connection.draft_id.is_(None))
    else:
        conn_q = conn_q.where(
            (Connection.draft_id.is_(None))
            | (Connection.draft_id == diagram.draft_id)
        )
    connections = list((await db.execute(conn_q)).scalars().all())

    tech_ids: set[uuid.UUID] = set()
    for p in placements:
        if p.object.technology_ids:
            tech_ids.update(p.object.technology_ids)
    for c in connections:
        if c.protocol_ids:
            tech_ids.update(c.protocol_ids)

    tech_names: dict[uuid.UUID, str] = {}
    if tech_ids:
        tech_q = select(Technology).where(Technology.id.in_(tech_ids))
        for t in (await db.execute(tech_q)).scalars().all():
            tech_names[t.id] = t.name

    return {
        "placements": placements,
        "connections": connections,
        "tech_names": tech_names,
    }


async def get_diagrams(
    db: AsyncSession,
    scope_object_id: uuid.UUID | None = None,
    include_drafts: bool = False,
    workspace_id: uuid.UUID | None = None,
) -> list[Diagram]:
    query = select(Diagram)
    if scope_object_id is not None:
        query = query.where(Diagram.scope_object_id == scope_object_id)
    if workspace_id is not None:
        query = query.where(Diagram.workspace_id == workspace_id)
    # Forked (draft-owned) diagrams are hidden from the default list so the
    # user doesn't see "(draft)" entries mixed into the main Diagrams page.
    if not include_drafts:
        query = query.where(Diagram.draft_id.is_(None))
    result = await db.execute(query.order_by(Diagram.name))
    return list(result.scalars().all())


async def get_diagram(db: AsyncSession, diagram_id: uuid.UUID) -> Diagram | None:
    result = await db.execute(
        select(Diagram)
        .where(Diagram.id == diagram_id)
        .options(selectinload(Diagram.objects))
    )
    return result.scalar_one_or_none()


async def create_diagram(
    db: AsyncSession,
    data: DiagramCreate,
    workspace_id: uuid.UUID | None = None,
) -> Diagram:
    diagram = Diagram(
        name=data.name,
        type=data.type,
        description=data.description,
        scope_object_id=data.scope_object_id,
        settings=data.settings,
        workspace_id=workspace_id,
    )
    db.add(diagram)
    await db.flush()
    await db.refresh(diagram)
    return diagram


async def update_diagram(
    db: AsyncSession, diagram: Diagram, data: DiagramUpdate
) -> Diagram:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(diagram, field, value)
    await db.flush()
    await db.refresh(diagram)
    return diagram


async def delete_diagram(db: AsyncSession, diagram: Diagram) -> None:
    await db.delete(diagram)
    await db.flush()


# ─── Diagram Objects (positions) ──────────────────────────


class DiagramObjectTargetMissingError(ValueError):
    """The object being placed on a diagram does not exist."""


async def get_diagram_objects(
    db: AsyncSession, diagram_id: uuid.UUID
) -> list[DiagramObject]:
    result = await db.execute(
        select(DiagramObject).where(DiagramObject.diagram_id == diagram_id)
    )
    return list(result.scalars().all())


async def get_diagrams_containing_object(
    db: AsyncSession, object_id: uuid.UUID
) -> list[Diagram]:
    result = await db.execute(
        select(Diagram)
        .join(DiagramObject, DiagramObject.diagram_id == Diagram.id)
        .where(DiagramObject.object_id == object_id)
        .distinct()
    )
    return list(result.scalars().all())


async def add_object_to_diagram(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    data: DiagramObjectCreate,
    *,
    actor_user=None,
    workspace_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> DiagramObject:
    target = await db.get(ModelObject, data.object_id)
    if target is None:
        raise DiagramObjectTargetMissingError(str(data.object_id))

    obj = DiagramObject(
        diagram_id=diagram_id,
        object_id=data.object_id,
        position_x=data.position_x,
        position_y=data.position_y,
        width=data.width,
        height=data.height,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    # Undo recording
    if (
        actor_user is not None
        and workspace_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=workspace_id,
            diagram_id=diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.DIAGRAM_OBJECT,
            target_id=obj.id,
            action=UndoAction.CREATE,
            forward_summary="Added object to diagram"[:80],
            inverse_payload={"target_id": str(obj.id)},
            after_state=activity_service.snapshot(obj, include_metadata=True),
            coalesce_key=f"diagram_object:{obj.id}:create",
        )

    return obj


async def update_diagram_object(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    data: DiagramObjectUpdate,
    *,
    actor_user=None,
    workspace_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> DiagramObject | None:
    result = await db.execute(
        select(DiagramObject).where(
            DiagramObject.diagram_id == diagram_id,
            DiagramObject.object_id == object_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        return None

    before = activity_service.snapshot(obj, include_metadata=True)
    update_data = data.model_dump(exclude_unset=True)
    # Strip undo-context fields
    update_data.pop("from_draft_id", None)
    for field, value in update_data.items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    after = activity_service.snapshot(obj, include_metadata=True)

    # Undo recording — separate coalesce keys for position vs size
    if (
        actor_user is not None
        and workspace_id is not None
    ):
        diff = activity_service.diff_snapshots(before, after)
        if diff:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            position_keys = {"position_x", "position_y"}
            size_keys = {"width", "height"}
            changed_keys = set(diff.keys())

            if changed_keys & position_keys:
                pos_diff = {k: diff[k] for k in diff if k in position_keys}
                await undo_service.record(
                    db,
                    user_id=actor_user.id,
                    workspace_id=workspace_id,
                    diagram_id=diagram_id,
                    draft_id=from_draft_id,
                    target_type=UndoTargetType.DIAGRAM_OBJECT,
                    target_id=obj.id,
                    action=UndoAction.UPDATE,
                    forward_summary="Moved object in diagram"[:80],
                    inverse_payload={"before": {k: v["before"] for k, v in pos_diff.items()}},
                    after_state={k: v["after"] for k, v in pos_diff.items()},
                    coalesce_key=f"diagram_object:{obj.id}:position",
                )

            if changed_keys & size_keys:
                size_diff = {k: diff[k] for k in diff if k in size_keys}
                await undo_service.record(
                    db,
                    user_id=actor_user.id,
                    workspace_id=workspace_id,
                    diagram_id=diagram_id,
                    draft_id=from_draft_id,
                    target_type=UndoTargetType.DIAGRAM_OBJECT,
                    target_id=obj.id,
                    action=UndoAction.UPDATE,
                    forward_summary="Resized object in diagram"[:80],
                    inverse_payload={"before": {k: v["before"] for k, v in size_diff.items()}},
                    after_state={k: v["after"] for k, v in size_diff.items()},
                    coalesce_key=f"diagram_object:{obj.id}:size",
                )

            # Any other changed fields (unlikely, but catch-all)
            other_diff = {k: diff[k] for k in diff if k not in position_keys | size_keys}
            if other_diff:
                await undo_service.record(
                    db,
                    user_id=actor_user.id,
                    workspace_id=workspace_id,
                    diagram_id=diagram_id,
                    draft_id=from_draft_id,
                    target_type=UndoTargetType.DIAGRAM_OBJECT,
                    target_id=obj.id,
                    action=UndoAction.UPDATE,
                    forward_summary="Updated diagram object"[:80],
                    inverse_payload={"before": {k: v["before"] for k, v in other_diff.items()}},
                    after_state={k: v["after"] for k, v in other_diff.items()},
                    coalesce_key=f"diagram_object:{obj.id}:{','.join(sorted(other_diff.keys()))}",
                )

    return obj


async def remove_object_from_diagram(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    *,
    actor_user=None,
    workspace_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> bool:
    result = await db.execute(
        select(DiagramObject).where(
            DiagramObject.diagram_id == diagram_id,
            DiagramObject.object_id == object_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        return False

    # Capture snapshot BEFORE delete — include metadata so restore_service
    # can reconstruct the placement on undo.
    snapshot = activity_service.snapshot(obj, include_metadata=True)
    do_id = obj.id

    await db.delete(obj)
    await db.flush()

    # Undo recording
    if (
        actor_user is not None
        and workspace_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=workspace_id,
            diagram_id=diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.DIAGRAM_OBJECT,
            target_id=do_id,
            action=UndoAction.DELETE,
            forward_summary="Removed object from diagram"[:80],
            inverse_payload={"snapshot": snapshot, "id": str(do_id)},
            after_state=None,
            coalesce_key=f"diagram_object:{do_id}:delete",
        )

    return True
