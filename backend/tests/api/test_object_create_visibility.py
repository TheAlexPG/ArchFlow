import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.v1.diagrams import add_object_to_diagram
from app.api.v1.objects import create_object as create_object_endpoint
from app.core.database import async_session
from app.models.activity_log import ActivityLog, ActivityTargetType
from app.models.object import ModelObject
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
