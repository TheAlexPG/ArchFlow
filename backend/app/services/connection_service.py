import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.schemas.connection import ConnectionCreate, ConnectionUpdate


async def get_connections(db: AsyncSession) -> list[Connection]:
    result = await db.execute(select(Connection))
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


async def create_connection(db: AsyncSession, data: ConnectionCreate) -> Connection:
    conn = Connection(
        source_id=data.source_id,
        target_id=data.target_id,
        label=data.label,
        protocol=data.protocol,
        direction=data.direction,
        tags=data.tags,
        source_handle=data.source_handle,
        target_handle=data.target_handle,
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


async def delete_connection(db: AsyncSession, conn: Connection) -> None:
    await db.delete(conn)
    await db.flush()
