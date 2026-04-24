import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_workspace_id
from app.core.database import get_db
from app.models.activity_log import ActivityLog, ActivityTargetType
from app.models.user import User
from app.schemas.activity import ActivityLogResponse

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityLogResponse])
async def list_activity(
    target_type: ActivityTargetType | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: uuid.UUID | None = Depends(get_current_workspace_id),
):
    """Global activity feed scoped to the currently-selected workspace.

    Reads the workspace from the ``X-Workspace-ID`` header (validated by
    ``get_current_workspace_id``).  Returns 400 when the caller does not
    belong to any workspace, mirroring the behaviour of other workspace-scoped
    endpoints.

    Server-side filtering keeps the response small on busy workspaces.
    """
    if workspace_id is None:
        raise HTTPException(
            status_code=400,
            detail="X-Workspace-ID header is required (or user has no workspace).",
        )

    query = select(ActivityLog).where(ActivityLog.workspace_id == workspace_id)
    if target_type is not None:
        query = query.where(ActivityLog.target_type == target_type)
    if user_id is not None:
        query = query.where(ActivityLog.user_id == user_id)
    query = query.order_by(ActivityLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return [ActivityLogResponse.model_validate(e) for e in result.scalars()]
