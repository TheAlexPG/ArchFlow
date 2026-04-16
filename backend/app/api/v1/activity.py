import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.activity_log import ActivityLog, ActivityTargetType
from app.schemas.activity import ActivityLogResponse

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityLogResponse])
async def list_activity(
    target_type: ActivityTargetType | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Global activity feed across objects/connections/diagrams.

    Powers the /activity audit page. Server-side filtering keeps the
    response small on busy workspaces.
    """
    query = select(ActivityLog)
    if target_type is not None:
        query = query.where(ActivityLog.target_type == target_type)
    if user_id is not None:
        query = query.where(ActivityLog.user_id == user_id)
    query = query.order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [ActivityLogResponse.model_validate(e) for e in result.scalars()]
