import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.draft import (
    DraftCreate,
    DraftFromDiagram,
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
    return await draft_service.create_draft(
        db, data, author_id=user.id if user else None
    )


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


@router.post("/{draft_id}/apply")
async def apply_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        return await draft_service.apply_draft(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{draft_id}/discard", response_model=DraftResponse)
async def discard_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await draft_service.discard_draft(db, draft)


@router.post(
    "/from-diagram/{diagram_id}", response_model=DraftResponse, status_code=201
)
async def create_draft_from_diagram(
    diagram_id: uuid.UUID,
    data: DraftFromDiagram,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Fork an existing diagram into a new draft. Returns the draft with
    ``forked_diagram_id`` set to the clone the user should navigate to."""
    try:
        draft, _forked = await draft_service.fork_existing_diagram(
            db,
            diagram_id,
            DraftCreate(name=data.name, description=data.description),
            author_id=user.id if user else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return draft
