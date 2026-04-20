from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.workspace import Role
from app.services import team_service

router = APIRouter(prefix="/workspaces/{workspace_id}/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str
    description: str | None = None


class TeamResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None


class TeamMemberResponse(BaseModel):
    user_id: UUID
    email: str
    name: str


class TeamMemberAdd(BaseModel):
    user_id: UUID


@router.get("", response_model=list[TeamResponse])
async def list_teams(
    workspace_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    rows = await team_service.list_teams(db, workspace_id)
    return [
        TeamResponse(
            id=t.id,
            workspace_id=t.workspace_id,
            name=t.name,
            slug=t.slug,
            description=t.description,
        )
        for t in rows
    ]


@router.post("", response_model=TeamResponse, status_code=201)
async def create_team(
    workspace_id: UUID,
    payload: TeamCreate,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    team = await team_service.create_team(
        db, workspace_id, payload.name, payload.description
    )
    return TeamResponse(
        id=team.id,
        workspace_id=team.workspace_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
    )


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    workspace_id: UUID,
    team_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    team = await team_service.get_team(db, workspace_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    await team_service.delete_team(db, team)


@router.get("/{team_id}/members", response_model=list[TeamMemberResponse])
async def list_members(
    workspace_id: UUID,
    team_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    team = await team_service.get_team(db, workspace_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    rows = await team_service.list_team_members(db, team.id)
    return [
        TeamMemberResponse(user_id=u.id, email=u.email, name=u.name)
        for _, u in rows
    ]


@router.post("/{team_id}/members", status_code=201)
async def add_member(
    workspace_id: UUID,
    team_id: UUID,
    payload: TeamMemberAdd,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    team = await team_service.get_team(db, workspace_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    try:
        await team_service.add_team_member(db, team, payload.user_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    team_id: UUID,
    user_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    team = await team_service.get_team(db, workspace_id, team_id)
    if team is None:
        raise HTTPException(404, "Team not found")
    ok = await team_service.remove_team_member(db, team.id, user_id)
    if not ok:
        raise HTTPException(404, "Not a member")
