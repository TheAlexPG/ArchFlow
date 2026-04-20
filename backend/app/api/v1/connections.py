import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.connection import ConnectionCreate, ConnectionResponse, ConnectionUpdate
from app.realtime.manager import fire_and_forget_publish
from app.services import connection_service, object_service
from app.services.webhook_service import fire_and_forget_emit

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    draft_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await connection_service.get_connections(db, draft_id=draft_id)


@router.get("/between", response_model=list[ConnectionResponse])
async def get_connections_between(
    src: uuid.UUID = Query(...),
    tgt: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await connection_service.get_connections_between(db, src, tgt)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(connection_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conn = await connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(
    data: ConnectionCreate,
    draft_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    source = await object_service.get_object(db, data.source_id)
    if not source:
        raise HTTPException(status_code=400, detail="Source object not found")
    target = await object_service.get_object(db, data.target_id)
    if not target:
        raise HTTPException(status_code=400, detail="Target object not found")
    conn = await connection_service.create_connection(db, data, draft_id=draft_id)
    if draft_id is None:
        body = ConnectionResponse.model_validate(conn).model_dump(mode="json")
        fire_and_forget_emit("connection.created", body)
        fire_and_forget_publish(
            getattr(source, "workspace_id", None),
            "connection.created",
            {"connection": body},
        )
    return conn


@router.put("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    conn = await connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn = await connection_service.update_connection(db, conn, data)
    if conn.draft_id is None:
        body = ConnectionResponse.model_validate(conn).model_dump(mode="json")
        fire_and_forget_emit("connection.updated", body)
        src = await object_service.get_object(db, conn.source_id)
        fire_and_forget_publish(
            getattr(src, "workspace_id", None),
            "connection.updated",
            {"connection": body},
        )
    return conn


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conn = await connection_service.get_connection(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    was_draft = conn.draft_id is not None
    conn_id_str = str(conn.id)
    src = await object_service.get_object(db, conn.source_id)
    src_ws_id = getattr(src, "workspace_id", None)
    await connection_service.delete_connection(db, conn)
    if not was_draft:
        fire_and_forget_emit("connection.deleted", {"id": conn_id_str})
        fire_and_forget_publish(src_ws_id, "connection.deleted", {"id": conn_id_str})
