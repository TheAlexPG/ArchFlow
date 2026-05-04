import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityTargetType
from app.models.connection import Connection
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


class DuplicateObjectError(ValueError):
    """Raised by :func:`create_object` when a live (non-draft) object with the
    same ``(workspace_id, type, lower(name))`` already exists.

    Carries the existing :class:`ModelObject` so callers (e.g. the agent's
    ``create_object`` tool wrapper) can return its id instead of failing the
    whole turn — the right behaviour for "reuse, don't duplicate" semantics.
    """

    def __init__(self, existing: ModelObject) -> None:
        super().__init__(
            f"object already exists: name={existing.name!r} type={getattr(existing.type, 'value', existing.type)!r} "
            f"id={existing.id} (use that id with place_on_diagram instead)"
        )
        self.existing = existing


async def create_object(
    db: AsyncSession,
    data: ObjectCreate,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> ModelObject:
    await validate_technology_ids(db, workspace_id, data.technology_ids)

    # Refuse silent duplicates on the live (non-draft) model. Drafts are
    # private workspaces; same-name copies there are intentional. For live
    # creates we look for ``(workspace_id, type, lower(name))`` and raise
    # :class:`DuplicateObjectError` carrying the existing row so the caller
    # can reuse it.
    if draft_id is None and data.name and data.name.strip():
        type_value = getattr(data.type, "value", data.type)
        from sqlalchemy import func as _func

        existing_q = select(ModelObject).where(
            ModelObject.draft_id.is_(None),
            ModelObject.type == type_value,
            _func.lower(ModelObject.name) == data.name.strip().lower(),
        )
        if workspace_id is not None:
            existing_q = existing_q.where(ModelObject.workspace_id == workspace_id)
        existing_row = (await db.execute(existing_q.limit(1))).scalar_one_or_none()
        if existing_row is not None:
            raise DuplicateObjectError(existing_row)

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
    return obj


async def update_object(
    db: AsyncSession, obj: ModelObject, data: ObjectUpdate
) -> ModelObject:
    if "technology_ids" in data.model_fields_set:
        await validate_technology_ids(db, obj.workspace_id, data.technology_ids)
    before = activity_service.snapshot(obj)
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata_" and value and obj.metadata_:
            # Merge metadata instead of replacing
            merged = {**obj.metadata_, **value}
            setattr(obj, field, merged)
        else:
            setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    after = activity_service.snapshot(obj)
    await activity_service.log_updated(
        db, ActivityTargetType.OBJECT, obj.id, before, after,
        workspace_id=obj.workspace_id,
    )
    return obj


async def delete_object(db: AsyncSession, obj: ModelObject) -> None:
    await activity_service.log_deleted(
        db, ActivityTargetType.OBJECT, obj, workspace_id=obj.workspace_id
    )
    await db.delete(obj)
    await db.flush()


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
