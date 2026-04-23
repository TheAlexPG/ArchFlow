import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.object import ModelObject
from app.schemas.connection import ConnectionCreate, ConnectionUpdate


async def get_connections(
    db: AsyncSession,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> list[Connection]:
    query = select(Connection)
    if draft_id is not None:
        query = query.where(
            (Connection.draft_id.is_(None)) | (Connection.draft_id == draft_id)
        )
    else:
        query = query.where(Connection.draft_id.is_(None))
    if workspace_id is not None:
        # Connections don't carry their own workspace_id — scope them via the
        # source object's workspace so switching workspaces never leaks edges
        # from another workspace.
        query = query.where(
            Connection.source_id.in_(
                select(ModelObject.id).where(ModelObject.workspace_id == workspace_id)
            )
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_connection(db: AsyncSession, connection_id: uuid.UUID) -> Connection | None:
    result = await db.execute(select(Connection).where(Connection.id == connection_id))
    return result.scalar_one_or_none()


async def get_connections_between(
    db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID
) -> list[Connection]:
    result = await db.execute(
        select(Connection).where(
            and_(Connection.source_id == source_id, Connection.target_id == target_id)
        )
    )
    return list(result.scalars().all())


async def create_connection(
    db: AsyncSession, data: ConnectionCreate, draft_id: uuid.UUID | None = None
) -> Connection:
    conn = Connection(
        source_id=data.source_id,
        target_id=data.target_id,
        label=data.label,
        protocol=data.protocol,
        direction=data.direction,
        tags=data.tags,
        source_handle=data.source_handle,
        target_handle=data.target_handle,
        shape=data.shape,
        label_size=data.label_size,
        via_object_ids=data.via_object_ids,
        draft_id=draft_id,
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)
    return conn


async def update_connection(
    db: AsyncSession, conn: Connection, data: ConnectionUpdate
) -> Connection:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conn, field, value)
    await db.flush()
    await db.refresh(conn)
    return conn


async def flip_connection(db: AsyncSession, conn: Connection) -> Connection:
    conn.source_id, conn.target_id = conn.target_id, conn.source_id
    conn.source_handle, conn.target_handle = conn.target_handle, conn.source_handle
    await db.flush()
    await db.refresh(conn)
    return conn


async def delete_connection(db: AsyncSession, conn: Connection) -> None:
    await db.delete(conn)
    await db.flush()
