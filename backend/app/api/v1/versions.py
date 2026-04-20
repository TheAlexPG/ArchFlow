from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permissions_dep import require_role
from app.api.workspace_dep import get_current_workspace
from app.core.database import get_db
from app.models.user import User
from app.models.version import VersionSource
from app.models.workspace import Role, Workspace
from app.services import version_service

router = APIRouter(prefix="/versions", tags=["versions"])


class VersionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    label: str
    source: str
    draft_id: UUID | None
    created_by_user_id: UUID | None
    created_at: datetime


class VersionDetailResponse(VersionResponse):
    snapshot_data: dict


class CompareRequest(BaseModel):
    a: UUID
    b: UUID


@router.get("", response_model=list[VersionResponse])
async def list_versions(
    workspace: Workspace = Depends(get_current_workspace),
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    rows = await version_service.list_versions(db, workspace.id)
    return [
        VersionResponse(
            id=v.id,
            workspace_id=v.workspace_id,
            label=v.label,
            source=v.source.value,
            draft_id=v.draft_id,
            created_by_user_id=v.created_by_user_id,
            created_at=v.created_at,
        )
        for v in rows
    ]


@router.post("/snapshot", response_model=VersionResponse, status_code=201)
async def create_manual_snapshot(
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Admin can freeze a snapshot at any time, not just on draft apply."""
    v = await version_service.create_snapshot(
        db,
        workspace_id=workspace.id,
        source=VersionSource.MANUAL,
        created_by_user_id=current_user.id,
    )
    return VersionResponse(
        id=v.id,
        workspace_id=v.workspace_id,
        label=v.label,
        source=v.source.value,
        draft_id=v.draft_id,
        created_by_user_id=v.created_by_user_id,
        created_at=v.created_at,
    )


@router.get("/{version_id}", response_model=VersionDetailResponse)
async def get_version(
    version_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    v = await version_service.get_version(db, workspace.id, version_id)
    if v is None:
        raise HTTPException(404, "Version not found")
    return VersionDetailResponse(
        id=v.id,
        workspace_id=v.workspace_id,
        label=v.label,
        source=v.source.value,
        draft_id=v.draft_id,
        created_by_user_id=v.created_by_user_id,
        created_at=v.created_at,
        snapshot_data=v.snapshot_data,
    )


@router.post("/compare")
async def compare_versions(
    payload: CompareRequest,
    workspace: Workspace = Depends(get_current_workspace),
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    a = await version_service.get_version(db, workspace.id, payload.a)
    b = await version_service.get_version(db, workspace.id, payload.b)
    if a is None or b is None:
        raise HTTPException(404, "One or both versions not found")
    diff = version_service.diff_snapshots(a.snapshot_data, b.snapshot_data)
    return {
        "a": {"id": str(a.id), "label": a.label, "created_at": a.created_at},
        "b": {"id": str(b.id), "label": b.label, "created_at": b.created_at},
        "diff": diff,
        "summary": version_service.summarize_diff(diff),
    }
