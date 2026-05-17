import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.v1.connections import (
    create_connection as create_connection_endpoint,
)
from app.api.v1.connections import (
    delete_connection as delete_connection_endpoint,
)
from app.api.v1.diagrams import add_object_to_diagram, remove_object_from_diagram
from app.api.v1.objects import create_object as create_object_endpoint
from app.core.database import async_session
from app.models.activity_log import ActivityLog, ActivityTargetType
from app.models.connection import Connection
from app.models.diagram import DiagramObject
from app.models.object import ModelObject, ObjectType
from app.schemas.connection import ConnectionCreate
from app.schemas.diagram import DiagramObjectCreate
from app.schemas.object import ObjectCreate


@pytest.mark.asyncio
async def test_create_object_commits_row_and_activity_before_return(db):
    name = f"Race visible {uuid.uuid4().hex}"
    response = await create_object_endpoint(
        ObjectCreate(name=name, type="system"),
        draft_id=None,
        db=db,
        current_user=None,
        x_workspace_id=None,
    )

    try:
        async with async_session() as other:
            obj = await other.get(ModelObject, response.id)
            assert obj is not None
            assert obj.name == name

            activity = (
                await other.execute(
                    select(ActivityLog).where(
                        ActivityLog.target_type == ActivityTargetType.OBJECT,
                        ActivityLog.target_id == response.id,
                    )
                )
            ).scalar_one_or_none()
            assert activity is not None
    finally:
        async with async_session() as cleanup:
            await cleanup.execute(
                delete(ActivityLog).where(ActivityLog.target_id == response.id)
            )
            await cleanup.execute(delete(ModelObject).where(ModelObject.id == response.id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_add_object_to_diagram_returns_404_for_missing_object(db, diagram):
    with pytest.raises(HTTPException) as exc_info:
        await add_object_to_diagram(
            diagram.id,
            DiagramObjectCreate(object_id=uuid.uuid4()),
            db=db,
            current_user=None,
            workspace_id=None,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Object not found"


@pytest.mark.asyncio
async def test_add_object_to_diagram_commits_before_return(db, diagram, workspace):
    obj = ModelObject(
        name=f"Placed {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add(obj)
    await db.flush()

    response = await add_object_to_diagram(
        diagram.id,
        DiagramObjectCreate(object_id=obj.id, position_x=10, position_y=20),
        db=db,
        current_user=None,
        workspace_id=None,
    )

    try:
        async with async_session() as other:
            placement = await other.get(DiagramObject, response.id)
            assert placement is not None
            assert placement.object_id == obj.id
    finally:
        async with async_session() as cleanup:
            await cleanup.execute(delete(ModelObject).where(ModelObject.id == obj.id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_remove_object_from_diagram_commits_before_return(db, diagram, workspace):
    obj = ModelObject(
        name=f"Removed {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add(obj)
    await db.flush()
    placement = DiagramObject(diagram_id=diagram.id, object_id=obj.id)
    db.add(placement)
    await db.commit()

    await remove_object_from_diagram(
        diagram.id,
        obj.id,
        from_draft_id=None,
        db=db,
        current_user=None,
        workspace_id=None,
    )

    try:
        async with async_session() as other:
            assert await other.get(DiagramObject, placement.id) is None
    finally:
        async with async_session() as cleanup:
            await cleanup.execute(delete(ModelObject).where(ModelObject.id == obj.id))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_create_connection_commits_before_return(db, workspace):
    source = ModelObject(
        name=f"Source {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    target = ModelObject(
        name=f"Target {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add_all([source, target])
    await db.flush()

    response = await create_connection_endpoint(
        ConnectionCreate(source_id=source.id, target_id=target.id),
        draft_id=None,
        db=db,
        current_user=None,
    )

    try:
        async with async_session() as other:
            conn = await other.get(Connection, response.id)
            assert conn is not None
            assert conn.source_id == source.id
            assert conn.target_id == target.id
    finally:
        async with async_session() as cleanup:
            await cleanup.execute(
                delete(ModelObject).where(ModelObject.id.in_([source.id, target.id]))
            )
            await cleanup.commit()


@pytest.mark.asyncio
async def test_delete_connection_commits_before_return(db, workspace):
    source = ModelObject(
        name=f"Source {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    target = ModelObject(
        name=f"Target {uuid.uuid4().hex}",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add_all([source, target])
    await db.flush()
    conn = Connection(source_id=source.id, target_id=target.id)
    db.add(conn)
    await db.commit()

    await delete_connection_endpoint(
        conn.id,
        from_diagram_id=None,
        from_draft_id=None,
        db=db,
        current_user=None,
    )

    try:
        async with async_session() as other:
            assert await other.get(Connection, conn.id) is None
    finally:
        async with async_session() as cleanup:
            await cleanup.execute(
                delete(ModelObject).where(ModelObject.id.in_([source.id, target.id]))
            )
            await cleanup.commit()
