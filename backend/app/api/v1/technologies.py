from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.technology import TechCategory
from app.models.user import User
from app.models.workspace import Role
from app.realtime.manager import fire_and_forget_publish
from app.schemas.technology import (
    TechnologyCreate,
    TechnologyDeleteConflict,
    TechnologyResponse,
    TechnologyUpdate,
)
from app.services import technology_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/technologies", tags=["technologies"]
)


@router.get("", response_model=list[TechnologyResponse])
async def list_technologies(
    workspace_id: UUID,
    q: str | None = Query(None, description="Fuzzy match over name / slug / aliases"),
    category: TechCategory | None = Query(None),
    scope: str = Query("all", pattern="^(all|builtin|custom)$"),
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    return await technology_service.list_technologies(
        db, workspace_id, q=q, category=category, scope=scope
    )


@router.post("", response_model=TechnologyResponse, status_code=201)
async def create_custom_technology(
    workspace_id: UUID,
    payload: TechnologyCreate,
    _: Role = Depends(require_role(Role.EDITOR)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        tech = await technology_service.create_custom(
            db, workspace_id, payload, user_id=user.id
        )
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(409, "A technology with this slug already exists") from e

    body = TechnologyResponse.model_validate(tech).model_dump(mode="json")
    fire_and_forget_publish(workspace_id, "technology.created", {"technology": body})
    return tech


@router.patch("/{technology_id}", response_model=TechnologyResponse)
async def update_custom_technology(
    workspace_id: UUID,
    technology_id: UUID,
    payload: TechnologyUpdate,
    _: Role = Depends(require_role(Role.EDITOR)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tech = await technology_service.get_technology(db, workspace_id, technology_id)
    if tech is None:
        raise HTTPException(404, "Technology not found")
    if tech.workspace_id is None:
        raise HTTPException(403, "Built-in technologies are read-only")
    tech = await technology_service.update_custom(db, tech, payload, user_id=user.id)
    body = TechnologyResponse.model_validate(tech).model_dump(mode="json")
    fire_and_forget_publish(workspace_id, "technology.updated", {"technology": body})
    return tech


@router.get("/{technology_id}/usage", response_model=TechnologyDeleteConflict)
async def technology_usage(
    workspace_id: UUID,
    technology_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    """Snapshot of how many objects / connections reference this tech.

    Pairs with the 409 response from DELETE — the management page can
    pre-check usage before offering a Delete button so the user isn't
    surprised by a blocked request.
    """
    tech = await technology_service.get_technology(db, workspace_id, technology_id)
    if tech is None:
        raise HTTPException(404, "Technology not found")
    obj_refs, conn_refs = await technology_service.count_references(db, tech.id)
    return TechnologyDeleteConflict(
        object_refs=obj_refs,
        connection_refs=conn_refs,
        detail=f"Referenced by {obj_refs} objects and {conn_refs} connections",
    )


@router.delete(
    "/{technology_id}",
    status_code=204,
    responses={
        409: {
            "model": TechnologyDeleteConflict,
            "description": "Technology is referenced by objects or connections",
        }
    },
)
async def delete_custom_technology(
    workspace_id: UUID,
    technology_id: UUID,
    _: Role = Depends(require_role(Role.EDITOR)),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tech = await technology_service.get_technology(db, workspace_id, technology_id)
    if tech is None:
        raise HTTPException(404, "Technology not found")
    if tech.workspace_id is None:
        raise HTTPException(403, "Built-in technologies are read-only")

    refs = await technology_service.delete_custom(db, tech, user_id=user.id)
    if refs is not None:
        obj_refs, conn_refs = refs
        raise HTTPException(
            409,
            detail={
                "object_refs": obj_refs,
                "connection_refs": conn_refs,
                "detail": "Technology is referenced by objects/connections",
            },
        )
    fire_and_forget_publish(
        workspace_id, "technology.deleted", {"id": str(technology_id)}
    )
