import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityTargetType
from app.models.connection import Connection
from app.models.object import ModelObject
from app.schemas.object import ObjectCreate, ObjectUpdate
from app.services import activity_service


async def get_objects(
    db: AsyncSession,
    type_filter: str | None = None,
    status_filter: str | None = None,
    parent_id: uuid.UUID | None = None,
) -> list[ModelObject]:
    query = select(ModelObject)
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


async def create_object(db: AsyncSession, data: ObjectCreate) -> ModelObject:
    obj = ModelObject(
        name=data.name,
        type=data.type,
        scope=data.scope,
        status=data.status,
        description=data.description,
        icon=data.icon,
        parent_id=data.parent_id,
        technology=data.technology,
        tags=data.tags,
        owner_team=data.owner_team,
        external_links=data.external_links,
        metadata_=data.metadata_,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await activity_service.log_created(db, ActivityTargetType.OBJECT, obj)
    return obj


async def update_object(
    db: AsyncSession, obj: ModelObject, data: ObjectUpdate
) -> ModelObject:
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
        db, ActivityTargetType.OBJECT, obj.id, before, after
    )
    return obj


async def delete_object(db: AsyncSession, obj: ModelObject) -> None:
    await activity_service.log_deleted(db, ActivityTargetType.OBJECT, obj)
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
