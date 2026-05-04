import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityTargetType
from app.models.connection import Connection
from app.models.diagram import DiagramObject
from app.models.object import ModelObject
from app.models.technology import Technology
from app.schemas.object import ObjectCreate, ObjectUpdate
from app.services import activity_service


async def validate_technology_ids(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    ids: list[uuid.UUID] | None,
) -> None:
    """Verify every id in `ids` is visible to this workspace (built-in or
    workspace-owned). Raises ValueError listing the offenders on failure."""
    if not ids:
        return
    result = await db.execute(
        select(Technology.id).where(
            Technology.id.in_(ids),
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            ),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(ids) - found
    if missing:
        raise ValueError(
            f"Unknown or cross-workspace technology_ids: {sorted(str(m) for m in missing)}"
        )


async def get_objects(
    db: AsyncSession,
    type_filter: str | None = None,
    status_filter: str | None = None,
    parent_id: uuid.UUID | None = None,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> list[ModelObject]:
    query = select(ModelObject)
    # Live queries hide draft-scoped objects. When a draft_id is passed we
    # include that draft's forked objects AND the live model, because a
    # forked diagram can reference either.
    if draft_id is not None:
        query = query.where(
            (ModelObject.draft_id.is_(None)) | (ModelObject.draft_id == draft_id)
        )
    else:
        query = query.where(ModelObject.draft_id.is_(None))
    if workspace_id is not None:
        query = query.where(ModelObject.workspace_id == workspace_id)
    if type_filter:
        query = query.where(ModelObject.type == type_filter)
    if status_filter:
        query = query.where(ModelObject.status == status_filter)
    if parent_id:
        query = query.where(ModelObject.parent_id == parent_id)
    result = await db.execute(query.order_by(ModelObject.name))
    return list(result.scalars().all())


async def get_object(db: AsyncSession, object_id: uuid.UUID) -> ModelObject | None:
    result = await db.execute(select(ModelObject).where(ModelObject.id == object_id))
    return result.scalar_one_or_none()


async def create_object(
    db: AsyncSession,
    data: ObjectCreate,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> ModelObject:
    await validate_technology_ids(db, workspace_id, data.technology_ids)
    obj = ModelObject(
        name=data.name,
        type=data.type,
        scope=data.scope,
        status=data.status,
        description=data.description,
        icon=data.icon,
        parent_id=data.parent_id,
        technology_ids=data.technology_ids,
        tags=data.tags,
        owner_team=data.owner_team,
        external_links=data.external_links,
        metadata_=data.metadata_,
        draft_id=draft_id,
        workspace_id=workspace_id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    # Only log activity for live objects; draft-scoped changes live
    # inside the draft until they're applied.
    if draft_id is None:
        await activity_service.log_created(
            db, ActivityTargetType.OBJECT, obj, workspace_id=workspace_id
        )

    # Undo recording — only for live objects with full context
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj.workspace_id is not None
        and draft_id is None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=obj.workspace_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.OBJECT,
            target_id=obj.id,
            action=UndoAction.CREATE,
            forward_summary=f"Created {(obj.name or '?')[:60]}"[:80],
            inverse_payload={"target_id": str(obj.id)},
            after_state=activity_service.snapshot(obj, include_metadata=True),
            coalesce_key=f"object:{obj.id}:create",
        )

    return obj


async def update_object(
    db: AsyncSession,
    obj: ModelObject,
    data: ObjectUpdate,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> ModelObject:
    if "technology_ids" in data.model_fields_set:
        await validate_technology_ids(db, obj.workspace_id, data.technology_ids)
    # Two snapshot pairs: activity log keeps metadata out of audit diffs,
    # undo needs metadata to detect metadata-only edits and round-trip them.
    before_for_log = activity_service.snapshot(obj)
    before_for_undo = activity_service.snapshot(obj, include_metadata=True)
    update_data = data.model_dump(exclude_unset=True)
    # Strip undo-context fields that are not object attributes
    update_data.pop("from_diagram_id", None)
    update_data.pop("from_draft_id", None)
    for field, value in update_data.items():
        if field == "metadata_" and value and obj.metadata_:
            # Merge metadata instead of replacing
            merged = {**obj.metadata_, **value}
            setattr(obj, field, merged)
        else:
            setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    after_for_log = activity_service.snapshot(obj)
    after_for_undo = activity_service.snapshot(obj, include_metadata=True)
    await activity_service.log_updated(
        db, ActivityTargetType.OBJECT, obj.id, before_for_log, after_for_log,
        workspace_id=obj.workspace_id,
    )

    # Undo recording
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj.workspace_id is not None
    ):
        diff = activity_service.diff_snapshots(before_for_undo, after_for_undo)
        if diff:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            await undo_service.record(
                db,
                user_id=actor_user.id,
                workspace_id=obj.workspace_id,
                diagram_id=from_diagram_id,
                draft_id=from_draft_id,
                target_type=UndoTargetType.OBJECT,
                target_id=obj.id,
                action=UndoAction.UPDATE,
                forward_summary=_summarise_object_diff(obj, diff),
                inverse_payload={"before": {k: v["before"] for k, v in diff.items()}},
                after_state={k: v["after"] for k, v in diff.items()},
                coalesce_key=f"object:{obj.id}:{','.join(sorted(diff.keys()))}",
            )

    return obj


async def delete_object(
    db: AsyncSession,
    obj: ModelObject,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> None:
    # Capture snapshot and placements BEFORE delete. Undo needs the full row
    # (including metadata_) so restore_service can rebuild the entity; the
    # activity log keeps its no-metadata default via log_deleted itself.
    snapshot = activity_service.snapshot(obj, include_metadata=True)
    obj_id = obj.id
    obj_ws_id = obj.workspace_id

    # Capture DiagramObject placements so restore_service can replay them
    placements_result = await db.execute(
        select(DiagramObject).where(DiagramObject.object_id == obj_id)
    )
    placements = list(placements_result.scalars().all())
    if placements:
        snapshot["_placements"] = [
            activity_service.snapshot(p, include_metadata=True) for p in placements
        ]

    await activity_service.log_deleted(
        db, ActivityTargetType.OBJECT, obj, workspace_id=obj_ws_id
    )
    await db.delete(obj)
    await db.flush()

    # Undo recording
    if (
        actor_user is not None
        and from_diagram_id is not None
        and obj_ws_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=obj_ws_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.OBJECT,
            target_id=obj_id,
            action=UndoAction.DELETE,
            forward_summary=f"Deleted {(snapshot.get('name') or '?')[:60]}"[:80],
            inverse_payload={"snapshot": snapshot, "id": str(obj_id)},
            after_state=None,
            coalesce_key=f"object:{obj_id}:delete",
        )


async def get_children(db: AsyncSession, object_id: uuid.UUID) -> list[ModelObject]:
    result = await db.execute(
        select(ModelObject)
        .where(ModelObject.parent_id == object_id)
        .order_by(ModelObject.name)
    )
    return list(result.scalars().all())


async def get_dependencies(
    db: AsyncSession, object_id: uuid.UUID
) -> dict[str, list]:
    """Get upstream and downstream dependencies for an object."""
    upstream_q = await db.execute(
        select(Connection)
        .where(Connection.target_id == object_id)
        .options(selectinload(Connection.source))
    )
    downstream_q = await db.execute(
        select(Connection)
        .where(Connection.source_id == object_id)
        .options(selectinload(Connection.target))
    )
    return {
        "upstream": list(upstream_q.scalars().all()),
        "downstream": list(downstream_q.scalars().all()),
    }


def _summarise_object_diff(obj: ModelObject, diff: dict) -> str:
    """Human-readable label for the history popover. Max ~80 chars."""
    fields = ", ".join(sorted(diff.keys()))
    name = (obj.name or "?")[:40]
    return f"Edited {name} — {fields}"[:80]
