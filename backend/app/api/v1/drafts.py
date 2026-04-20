import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.models.draft import DraftDiagram
from app.models.user import User
from app.schemas.draft import (
    DraftCreate,
    DraftDiagramResponse,
    DraftDiffResponse,
    DraftDiffSummary,
    DraftFromDiagram,
    DraftResponse,
    DraftUpdate,
    PerDiagramDiff,
)
from app.services import draft_service

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _build_draft_response(draft) -> DraftResponse:
    """Populate DraftDiagramResponse.source_diagram_name / forked_diagram_name
    from the eagerly-loaded relationships."""
    diagram_responses = []
    for dd in (draft.diagrams or []):
        src_name = (
            dd.source_diagram.name if dd.source_diagram is not None else None
        )
        fork_name = (
            dd.forked_diagram.name if dd.forked_diagram is not None else None
        )
        diagram_responses.append(
            DraftDiagramResponse(
                id=dd.id,
                draft_id=dd.draft_id,
                source_diagram_id=dd.source_diagram_id,
                forked_diagram_id=dd.forked_diagram_id,
                source_diagram_name=src_name,
                forked_diagram_name=fork_name,
                created_at=dd.created_at,
            )
        )
    return DraftResponse(
        id=draft.id,
        name=draft.name,
        description=draft.description,
        status=draft.status,
        author_id=draft.author_id,
        diagrams=diagram_responses,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _build_diff_response(diff_data: dict) -> DraftDiffResponse:
    per_diagram = []
    for d in diff_data.get("diagrams", []):
        per_diagram.append(
            PerDiagramDiff(
                source_diagram_id=d["source_diagram_id"],
                forked_diagram_id=d["forked_diagram_id"],
                source_diagram_name=d.get("source_diagram_name"),
                forked_diagram_name=d.get("forked_diagram_name"),
                source_objects=d.get("source_objects", {}),
                fork_objects=d.get("fork_objects", {}),
                source_connections=d.get("source_connections", {}),
                fork_connections=d.get("fork_connections", {}),
                moved_on_fork=d.get("moved_on_fork", []),
                resized_on_fork=d.get("resized_on_fork", []),
                object_names=d.get("object_names", {}),
                summary=DraftDiffSummary(**d["summary"]),
            )
        )
    total = diff_data.get("total_summary", {})
    return DraftDiffResponse(
        total_summary=DraftDiffSummary(**total),
        per_diagram=per_diagram,
    )


@router.get("", response_model=list[DraftResponse])
async def list_drafts(db: AsyncSession = Depends(get_db)):
    drafts = await draft_service.list_drafts(db)
    return [_build_draft_response(d) for d in drafts]


@router.post("", response_model=DraftResponse, status_code=201)
async def create_draft(
    data: DraftCreate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    draft = await draft_service.create_draft(
        db, data, author_id=user.id if user else None
    )
    return _build_draft_response(draft)


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _build_draft_response(draft)


@router.put("/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: uuid.UUID,
    data: DraftUpdate,
    db: AsyncSession = Depends(get_db),
):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = await draft_service.update_draft(db, draft, data)
    return _build_draft_response(draft)


@router.delete("/{draft_id}", status_code=204)
async def delete_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await draft_service.delete_draft(db, draft)


@router.post("/{draft_id}/apply")
async def apply_draft(
    draft_id: uuid.UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Merge a draft onto main.

    If the draft's base_version has drifted from current main (someone
    else changed the same objects in parallel), we return 409 with the
    conflict report. Caller can inspect it and resubmit with `?force=true`
    to overwrite.
    """
    from app.services import conflict_service
    from app.services.webhook_service import fire_and_forget_emit

    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        result = await conflict_service.apply_with_snapshot(
            db, draft, current_user_id=None, force=force
        )
    except conflict_service.ConflictError as e:
        raise HTTPException(status_code=409, detail=e.report) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    fire_and_forget_emit(
        "draft.applied", {"id": str(draft.id), "name": getattr(draft, "name", None)}
    )
    return result


@router.get("/{draft_id}/conflicts")
async def draft_conflicts(
    draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """Inspect whether this draft would collide with current main. UI
    calls this before enabling the "Apply" button."""
    from app.services import conflict_service

    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return await conflict_service.compute_conflicts(db, draft)


@router.get("/{draft_id}/diff", response_model=DraftDiffResponse)
async def get_draft_diff(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        diff_data = await draft_service.compute_diff(db, draft)
        return _build_diff_response(diff_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{draft_id}/discard", response_model=DraftResponse)
async def discard_draft(draft_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    await draft_service.discard_draft(db, draft)
    # Re-fetch with relationships properly loaded after discard.
    draft = await draft_service.get_draft(db, draft_id)
    return _build_draft_response(draft)


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
    one DraftDiagram pointing at the fork clone."""
    try:
        draft, _dd = await draft_service.fork_existing_diagram(
            db,
            diagram_id,
            DraftCreate(name=data.name, description=data.description),
            author_id=user.id if user else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _build_draft_response(draft)


@router.post(
    "/{draft_id}/diagrams/{diagram_id}",
    response_model=DraftDiagramResponse,
    status_code=201,
)
async def add_diagram_to_draft(
    draft_id: uuid.UUID,
    diagram_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Add a live diagram to an existing open draft, creating a fork clone."""
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        dd = await draft_service.add_diagram_to_draft(db, draft, diagram_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Load names for the response.
    dd_loaded = (
        await db.execute(
            select(DraftDiagram)
            .where(DraftDiagram.id == dd.id)
            .options(
                selectinload(DraftDiagram.source_diagram),
                selectinload(DraftDiagram.forked_diagram),
            )
        )
    ).scalar_one()

    return DraftDiagramResponse(
        id=dd_loaded.id,
        draft_id=dd_loaded.draft_id,
        source_diagram_id=dd_loaded.source_diagram_id,
        forked_diagram_id=dd_loaded.forked_diagram_id,
        source_diagram_name=dd_loaded.source_diagram.name if dd_loaded.source_diagram else None,
        forked_diagram_name=dd_loaded.forked_diagram.name if dd_loaded.forked_diagram else None,
        created_at=dd_loaded.created_at,
    )


@router.delete("/{draft_id}/diagrams/{diagram_id}", status_code=204)
async def remove_diagram_from_draft(
    draft_id: uuid.UUID,
    diagram_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a diagram (by source_diagram_id) from the draft and delete its fork."""
    draft = await draft_service.get_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        await draft_service.remove_diagram_from_draft(db, draft, diagram_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
