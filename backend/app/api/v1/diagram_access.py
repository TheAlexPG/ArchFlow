from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.diagram import Diagram
from app.models.team import AccessLevel
from app.models.workspace import Role
from app.services import access_service

router = APIRouter(prefix="/diagrams/{diagram_id}/access", tags=["diagram-access"])


class TeamGrantRequest(BaseModel):
    team_id: UUID
    level: AccessLevel = AccessLevel.READ


class UserGrantRequest(BaseModel):
    user_id: UUID
    level: AccessLevel = AccessLevel.READ


class GrantResponse(BaseModel):
    """One grant row. Exactly one of team_id / user_id is non-null."""

    team_id: UUID | None
    user_id: UUID | None
    access_level: str


async def _diagram_or_404(db: AsyncSession, diagram_id: UUID) -> Diagram:
    diagram = (
        await db.execute(select(Diagram).where(Diagram.id == diagram_id))
    ).scalar_one_or_none()
    if diagram is None:
        raise HTTPException(404, "Diagram not found")
    return diagram


@router.get("", response_model=list[GrantResponse])
async def list_grants(
    diagram_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    grants = await access_service.list_diagram_grants(db, diagram_id)
    return [
        GrantResponse(
            team_id=g.team_id,
            user_id=g.user_id,
            access_level=g.access_level.value,
        )
        for g in grants
    ]


@router.post("/teams", response_model=GrantResponse, status_code=201)
async def grant_team(
    diagram_id: UUID,
    payload: TeamGrantRequest,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    g = await access_service.grant_team_access(
        db, diagram_id, payload.team_id, payload.level
    )
    return GrantResponse(
        team_id=g.team_id, user_id=g.user_id, access_level=g.access_level.value
    )


@router.delete("/teams/{team_id}", status_code=204)
async def revoke_team(
    diagram_id: UUID,
    team_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    ok = await access_service.revoke_team_access(db, diagram_id, team_id)
    if not ok:
        raise HTTPException(404, "Grant not found")


@router.post("/users", response_model=GrantResponse, status_code=201)
async def grant_user(
    diagram_id: UUID,
    payload: UserGrantRequest,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    g = await access_service.grant_user_access(
        db, diagram_id, payload.user_id, payload.level
    )
    return GrantResponse(
        team_id=g.team_id, user_id=g.user_id, access_level=g.access_level.value
    )


@router.delete("/users/{user_id}", status_code=204)
async def revoke_user(
    diagram_id: UUID,
    user_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    ok = await access_service.revoke_user_access(db, diagram_id, user_id)
    if not ok:
        raise HTTPException(404, "Grant not found")


