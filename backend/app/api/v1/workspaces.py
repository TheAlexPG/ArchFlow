from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.schemas.workspace import WorkspaceResponse
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await workspace_service.list_user_workspaces(db, current_user.id)
    memberships = await db.execute(
        select(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    )
    role_by_ws = {m.workspace_id: m.role.value for m in memberships.scalars().all()}
    return [
        WorkspaceResponse(
            id=w.id,
            org_id=w.org_id,
            name=w.name,
            slug=w.slug,
            role=role_by_ws.get(w.id, "viewer"),
            created_at=w.created_at,
        )
        for w in rows
    ]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await workspace_service.get_user_membership(
        db, current_user.id, workspace_id
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    from app.models.workspace import Workspace

    ws = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    assert ws is not None
    return WorkspaceResponse(
        id=ws.id,
        org_id=ws.org_id,
        name=ws.name,
        slug=ws.slug,
        role=membership.role.value,
        created_at=ws.created_at,
    )
