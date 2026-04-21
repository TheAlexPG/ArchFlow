from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import Role, WorkspaceMember
from app.schemas.workspace import WorkspaceResponse
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreateRequest(BaseModel):
    name: str


class WorkspaceRenameRequest(BaseModel):
    name: str


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


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        ws, member = await workspace_service.create_workspace(
            db, current_user, payload.name
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return WorkspaceResponse(
        id=ws.id,
        org_id=ws.org_id,
        name=ws.name,
        slug=ws.slug,
        role=member.role.value,
        created_at=ws.created_at,
    )


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


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def rename_workspace(
    workspace_id: UUID,
    payload: WorkspaceRenameRequest,
    role: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        ws = await workspace_service.rename_workspace(db, workspace_id, payload.name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return WorkspaceResponse(
        id=ws.id,
        org_id=ws.org_id,
        name=ws.name,
        slug=ws.slug,
        role=role.value,
        created_at=ws.created_at,
    )


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    _: Role = Depends(require_role(Role.OWNER)),
    db: AsyncSession = Depends(get_db),
):
    try:
        await workspace_service.delete_workspace(
            db, workspace_id, current_user.id
        )
    except workspace_service.WorkspaceHasContentError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
