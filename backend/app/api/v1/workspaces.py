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
from app.services import repo_credentials_service, workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class GitHubTokenRequest(BaseModel):
    token: str | None = None


class GitHubTokenStatusResponse(BaseModel):
    linked: bool
    github_login: str | None = None


class GitHubTokenTestRequest(BaseModel):
    """Optional token override — if absent, tests the stored token."""

    token: str | None = None


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


# ---------------------------------------------------------------------------
# GitHub token endpoints
# ---------------------------------------------------------------------------


async def _ensure_workspace_membership(
    workspace_id: UUID, user: User, db: AsyncSession
) -> WorkspaceMember:
    """Cheap re-check that the path workspace_id matches the caller's
    membership. The OWNER role gate uses ``get_current_workspace`` which
    relies on the X-Workspace-ID header — but the github-token endpoints
    are addressed by path, so we double-check the ID matches here.
    """
    membership = await workspace_service.get_user_membership(
        db, user.id, workspace_id
    )
    if membership is None:
        raise HTTPException(404, "Workspace not found")
    return membership


def _require_owner(role: Role) -> None:
    if role != Role.OWNER:
        raise HTTPException(
            403, f"Requires owner (you are {role.value})"
        )


async def _validate_and_extract_login(token: str) -> str | None:
    """Helper — calls validate_token and returns the github login on success."""
    try:
        payload = await repo_credentials_service.validate_token(token)
    except repo_credentials_service.GitHubServerError as e:
        raise HTTPException(502, f"GitHub upstream error: {e}") from e
    except repo_credentials_service.GitHubRateLimitError as e:
        raise HTTPException(429, str(e)) from e
    if payload is None:
        return None
    login = payload.get("login")
    return str(login) if login is not None else None


@router.post(
    "/{workspace_id}/github-token", response_model=GitHubTokenStatusResponse
)
async def set_github_token(
    workspace_id: UUID,
    payload: GitHubTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _ensure_workspace_membership(
        workspace_id, current_user, db
    )
    _require_owner(membership.role)
    if not payload.token or not payload.token.strip():
        raise HTTPException(
            422,
            detail={"error": "missing_token", "message": "token is required"},
        )
    login = await _validate_and_extract_login(payload.token)
    if login is None:
        raise HTTPException(
            422,
            detail={
                "error": "invalid_token",
                "message": "GitHub rejected this token (401)",
            },
        )
    try:
        await workspace_service.set_github_token(
            db, workspace_id, payload.token.strip()
        )
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return GitHubTokenStatusResponse(linked=True, github_login=login)


@router.delete("/{workspace_id}/github-token", status_code=204)
async def clear_github_token(
    workspace_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _ensure_workspace_membership(
        workspace_id, current_user, db
    )
    _require_owner(membership.role)
    await workspace_service.clear_github_token(db, workspace_id)
    return None


@router.post(
    "/{workspace_id}/github-token/test",
    response_model=GitHubTokenStatusResponse,
)
async def test_github_token(
    workspace_id: UUID,
    payload: GitHubTokenTestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    membership = await _ensure_workspace_membership(
        workspace_id, current_user, db
    )
    _require_owner(membership.role)
    token = (payload.token or "").strip()
    if not token:
        stored = await workspace_service.get_github_token(db, workspace_id)
        if stored is None:
            return GitHubTokenStatusResponse(linked=False, github_login=None)
        token = stored
    login = await _validate_and_extract_login(token)
    if login is None:
        return GitHubTokenStatusResponse(linked=False, github_login=None)
    return GitHubTokenStatusResponse(linked=True, github_login=login)
