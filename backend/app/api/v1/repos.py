"""Lightweight HTTP wrappers around RepoCredentialsService.

Used by the C4 inspector to validate ``repo_url`` on blur — backend
proxies the call so the workspace's GitHub token never ships to the
browser.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.workspace_dep import get_current_workspace
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import object_service, repo_credentials_service, workspace_service

router = APIRouter(prefix="/repos", tags=["repos"])


class RepoLookupRequest(BaseModel):
    repo_url: str


class RepoLookupResponse(BaseModel):
    repo_url: str  # canonical https://github.com/{owner}/{name}
    full_name: str  # owner/name
    description: str | None = None
    default_branch: str | None = None
    stargazers_count: int | None = None
    private: bool | None = None
    html_url: str | None = None


@router.post("/lookup", response_model=RepoLookupResponse)
async def lookup_repo(
    payload: RepoLookupRequest,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    # Membership is already enforced by ``get_current_workspace``. Any
    # workspace member may call this — read-only.
    try:
        canonical, full_name = object_service.normalize_repo_url(payload.repo_url)
    except object_service.InvalidRepoUrlError as exc:
        raise HTTPException(
            422,
            detail={"error": "invalid_repo_url", "message": str(exc)},
        ) from exc

    owner, name = full_name.split("/", 1)

    token = await workspace_service.get_github_token(db, workspace.id)
    if token is None:
        raise HTTPException(
            422,
            detail={
                "error": "no_github_token",
                "message": (
                    "Add a GitHub token in workspace settings to validate "
                    "repo links."
                ),
            },
        )

    try:
        meta: dict[str, Any] = await repo_credentials_service.lookup_repo(
            db, workspace.id, owner, name
        )
    except repo_credentials_service.GitHubAuthError as exc:
        raise HTTPException(
            422,
            detail={
                "error": "unauthorized",
                "message": "The workspace's GitHub token was rejected.",
            },
        ) from exc
    except repo_credentials_service.GitHubNotFoundError as exc:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": str(exc)},
        ) from exc
    except repo_credentials_service.GitHubRateLimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except repo_credentials_service.GitHubServerError as exc:
        raise HTTPException(502, f"GitHub upstream error: {exc}") from exc

    return RepoLookupResponse(
        repo_url=canonical,
        full_name=meta.get("full_name") or full_name,
        description=meta.get("description"),
        default_branch=meta.get("default_branch"),
        stargazers_count=meta.get("stargazers_count"),
        private=meta.get("private"),
        html_url=meta.get("html_url"),
    )
