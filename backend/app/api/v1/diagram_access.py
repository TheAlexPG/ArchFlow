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


class GrantRequest(BaseModel):
    team_id: UUID
    level: AccessLevel = AccessLevel.READ


class GrantResponse(BaseModel):
    team_id: UUID
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
        GrantResponse(team_id=g.team_id, access_level=g.access_level.value)
        for g in grants
    ]


@router.post("", response_model=GrantResponse, status_code=201)
async def grant(
    diagram_id: UUID,
    payload: GrantRequest,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    grant = await access_service.grant_team_access(
        db, diagram_id, payload.team_id, payload.level
    )
    return GrantResponse(team_id=grant.team_id, access_level=grant.access_level.value)


@router.delete("/{team_id}", status_code=204)
async def revoke(
    diagram_id: UUID,
    team_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await _diagram_or_404(db, diagram_id)
    ok = await access_service.revoke_team_access(db, diagram_id, team_id)
    if not ok:
        raise HTTPException(404, "Grant not found")
