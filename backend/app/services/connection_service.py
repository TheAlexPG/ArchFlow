import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.object import ModelObject
from app.models.technology import Technology
from app.schemas.connection import ConnectionCreate, ConnectionUpdate


async def _validate_protocol_ids(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    protocol_ids: list[uuid.UUID] | None,
) -> None:
    if not protocol_ids:
        return
    result = await db.execute(
        select(Technology.id).where(
            Technology.id.in_(protocol_ids),
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            ),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(protocol_ids) - found
    if missing:
        raise ValueError(
            "Unknown or cross-workspace protocol_ids: "
            f"{sorted(str(m) for m in missing)}"
        )


async def _source_workspace_id(
    db: AsyncSession, source_id: uuid.UUID
) -> uuid.UUID | None:
    """The connection inherits its scope from the source object's workspace."""
    result = await db.execute(
        select(ModelObject.workspace_id).where(ModelObject.id == source_id)
    )
    return result.scalar_one_or_none()


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
    ws_id = await _source_workspace_id(db, data.source_id)
    await _validate_protocol_ids(db, ws_id, data.protocol_ids)

    conn = Connection(
        source_id=data.source_id,
        target_id=data.target_id,
        label=data.label,
        protocol_ids=data.protocol_ids,
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
    if "protocol_ids" in data.model_fields_set:
        ws_id = await _source_workspace_id(db, conn.source_id)
        await _validate_protocol_ids(db, ws_id, data.protocol_ids)

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
