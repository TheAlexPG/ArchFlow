import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.draft import (
    DraftCreate,
    DraftItemCreate,
    DraftItemResponse,
    DraftItemUpdate,
    DraftResponse,
    DraftUpdate,
)
from app.services import draft_service

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftResponse])
async def list_drafts(db: AsyncSession = Depends(get_db)):
    return await draft_service.list_drafts(db)


@router.post("", response_model=DraftResponse, status_code=201)
async def create_draft(
    data: DraftCreate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    author_id = user.id if user else None
    return await draft_service.create_draft(db, data, author_id=author_id)


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.put("/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: uuid.UUID,
    data: DraftUpdate,
    db: AsyncSession = Depends(get_db),
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await draft_service.update_draft(db, draft, data)


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await draft_service.delete_draft(db, draft)


@router.post(
    "/{draft_id}/items",
    response_model=DraftItemResponse,
    status_code=201,
)
async def add_draft_item(
    draft_id: uuid.UUID,
    data: DraftItemCreate,
    db: AsyncSession = Depends(get_db),
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await draft_service.add_item(db, draft, data)


@router.put(
    "/{draft_id}/items/{item_id}", response_model=DraftItemResponse
)
async def update_draft_item(
    draft_id: uuid.UUID,
    item_id: uuid.UUID,
    data: DraftItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    item = next((i for i in draft.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in draft")
    return await draft_service.update_item(db, item, data)


@router.delete("/{draft_id}/items/{item_id}", status_code=204)
async def delete_draft_item(
    draft_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    item = next((i for i in draft.items if i.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in draft")
    await draft_service.delete_item(db, item)


@router.post("/{draft_id}/apply")
async def apply_draft(
    draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        return await draft_service.apply_draft(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{draft_id}/discard", response_model=DraftResponse)
async def discard_draft(
    draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await draft_service.discard_draft(db, draft)
