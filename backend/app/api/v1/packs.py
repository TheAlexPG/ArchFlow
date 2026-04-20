from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.workspace import Role
from app.services import pack_service

router = APIRouter(prefix="/workspaces/{workspace_id}/packs", tags=["packs"])


class PackCreate(BaseModel):
    name: str


class PackUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None


class PackResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


class ReorderPacksBody(BaseModel):
    ordered_ids: list[UUID]


@router.get("", response_model=list[PackResponse])
async def list_packs(
    workspace_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    return await pack_service.list_packs(db, workspace_id)


@router.post("", response_model=PackResponse, status_code=201)
async def create_pack(
    workspace_id: UUID,
    payload: PackCreate,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    return await pack_service.create_pack(db, workspace_id, payload.name)


@router.patch("/{pack_id}", response_model=PackResponse)
async def update_pack(
    workspace_id: UUID,
    pack_id: UUID,
    payload: PackUpdate,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    pack = await pack_service.get_pack(db, workspace_id, pack_id)
    if pack is None:
        raise HTTPException(404, "Pack not found")
    return await pack_service.update_pack(db, pack, payload.name, payload.sort_order)


@router.delete("/{pack_id}", status_code=204)
async def delete_pack(
    workspace_id: UUID,
    pack_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    pack = await pack_service.get_pack(db, workspace_id, pack_id)
    if pack is None:
        raise HTTPException(404, "Pack not found")
    await pack_service.delete_pack(db, pack)


@router.put("/reorder", status_code=204)
async def reorder_packs(
    workspace_id: UUID,
    payload: ReorderPacksBody,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    await pack_service.reorder_packs(db, workspace_id, payload.ordered_ids)
