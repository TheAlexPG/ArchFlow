"""REST endpoints for per-user undo / redo / history.

Auth guard pattern: `get_current_user` raises 401 if no valid token, then we
do an inline diagram fetch + workspace-membership check — the same pattern used
by `diagrams.py` for guarded GET/PUT routes (no `require_diagram_edit` dep
exists in this repo). Editing connections on a diagram (`connections.py`) is
actually unguarded, but undo mutations are user-specific and must reject
callers who don't own the workspace, so we enforce membership here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.undo import (
    UndoActionRequest,
    UndoActionResponse,
    UndoEntryRead,
    UndoHistoryResponse,
    UndoToRequest,
    UndoToResponse,
)
from app.realtime.manager import (
    fire_and_forget_publish_diagram,
    fire_and_forget_publish_user,
)
from app.services import undo_service
from app.services.undo_service import (
    UndoConcurrencyError,
    UndoEntryNotFound,
    UndoStackEmpty,
)

router = APIRouter(prefix="/diagrams/{diagram_id}", tags=["undo"])


async def _get_diagram_or_404(db: AsyncSession, diagram_id: uuid.UUID):
    """Fetch diagram and raise 404 if missing. Callers enforce workspace guard."""
    from app.services import diagram_service

    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diagram


def _broadcast_diagram_refetch(
    diagram_id: uuid.UUID, draft_id: uuid.UUID | None, reason: str
) -> None:
    """Tell every client on this diagram to invalidate entity caches.

    The undo apply path mutates the DB directly via setattr/db.delete/db.add
    and skips the per-route entity events (`object.updated`, etc.) that the
    frontend's diagram socket uses to refresh React Query caches. Without
    this broadcast, the actor's canvas (and every other tab on the diagram)
    keeps showing pre-undo state until a manual refresh.
    """
    fire_and_forget_publish_diagram(
        diagram_id,
        "diagram.refetch",
        {
            "diagram_id": str(diagram_id),
            "draft_id": str(draft_id) if draft_id else None,
            "reason": reason,
        },
    )


async def _require_workspace_member(db: AsyncSession, user: User, diagram) -> None:
    """Ensure `user` is a member of the diagram's workspace, else 403.

    Mirrors the membership check in diagrams.py get_diagram — we need the
    caller to be in the workspace before they can undo actions on its diagrams.
    """
    from app.services import workspace_service

    if diagram.workspace_id is None:
        # Unscoped diagrams (no workspace) — allow any authenticated user.
        return
    membership = await workspace_service.get_user_membership(
        db, user.id, diagram.workspace_id
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")


@router.post("/undo")
async def undo_endpoint(
    diagram_id: uuid.UUID,
    body: UndoActionRequest,
    draft_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    diagram = await _get_diagram_or_404(db, diagram_id)
    await _require_workspace_member(db, user, diagram)

    try:
        result = await undo_service.undo(
            db,
            user_id=user.id,
            diagram_id=diagram_id,
            draft_id=draft_id,
            actor_user=user,
            expected_seq=body.expected_seq,
        )
    except UndoStackEmpty:
        return Response(status_code=204)
    except UndoConcurrencyError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "undo_seq_mismatch", "actual_seq": e.actual_seq},
        )

    await db.commit()
    fire_and_forget_publish_user(user.id, "user.undo", {
        "diagram_id": str(diagram_id),
        "draft_id": str(draft_id) if draft_id else None,
        "entry_id": str(result.undone_entry.id) if result.undone_entry else None,
        "cursor_seq": result.cursor_seq,
        "redo_count": result.redo_count,
    })
    # Tell every client on the diagram (including the actor's own canvas)
    # to refresh entity caches — _apply_* mutates the DB directly and
    # bypasses the per-route entity events that normally drive cache
    # invalidation, so without this signal the canvas/sidebar stays stale.
    _broadcast_diagram_refetch(diagram_id, draft_id, "undo")
    return UndoActionResponse(
        undone_entry=(
            UndoEntryRead.model_validate(result.undone_entry)
            if result.undone_entry
            else None
        ),
        redone_entry=None,
        cursor_seq=result.cursor_seq,
        remaining_undo_count=result.remaining_undo_count,
        redo_count=result.redo_count,
    )


@router.post("/redo")
async def redo_endpoint(
    diagram_id: uuid.UUID,
    body: UndoActionRequest,
    draft_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    diagram = await _get_diagram_or_404(db, diagram_id)
    await _require_workspace_member(db, user, diagram)

    try:
        result = await undo_service.redo(
            db,
            user_id=user.id,
            diagram_id=diagram_id,
            draft_id=draft_id,
            actor_user=user,
            expected_seq=body.expected_seq,
        )
    except UndoStackEmpty:
        return Response(status_code=204)
    except UndoConcurrencyError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "redo_seq_mismatch", "actual_seq": e.actual_seq},
        )

    await db.commit()
    fire_and_forget_publish_user(user.id, "user.redo", {
        "diagram_id": str(diagram_id),
        "draft_id": str(draft_id) if draft_id else None,
        "entry_id": str(result.redone_entry.id) if result.redone_entry else None,
        "cursor_seq": result.cursor_seq,
        "redo_count": result.redo_count,
    })
    _broadcast_diagram_refetch(diagram_id, draft_id, "redo")
    return UndoActionResponse(
        undone_entry=None,
        redone_entry=(
            UndoEntryRead.model_validate(result.redone_entry)
            if result.redone_entry
            else None
        ),
        cursor_seq=result.cursor_seq,
        remaining_undo_count=result.remaining_undo_count,
        redo_count=result.redo_count,
    )


@router.get("/history", response_model=UndoHistoryResponse)
async def history_endpoint(
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    diagram = await _get_diagram_or_404(db, diagram_id)
    await _require_workspace_member(db, user, diagram)

    h = await undo_service.history(
        db,
        user_id=user.id,
        diagram_id=diagram_id,
        draft_id=draft_id,
        limit=limit,
    )
    return UndoHistoryResponse(
        entries=[UndoEntryRead.model_validate(e) for e in h.entries],
        cursor_seq=h.cursor_seq,
    )


@router.post("/undo-to/{entry_id}")
async def undo_to_endpoint(
    diagram_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: UndoToRequest,
    draft_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    diagram = await _get_diagram_or_404(db, diagram_id)
    await _require_workspace_member(db, user, diagram)

    try:
        res = await undo_service.undo_to(
            db,
            user_id=user.id,
            diagram_id=diagram_id,
            draft_id=draft_id,
            actor_user=user,
            entry_id=entry_id,
            expected_path_length=body.expected_path_length,
        )
    except UndoEntryNotFound:
        raise HTTPException(
            status_code=404, detail={"code": "undo_entry_not_found"}
        )
    except UndoConcurrencyError as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "undo_to_path_mismatch", "actual_seq": e.actual_seq},
        )

    await db.commit()
    fire_and_forget_publish_user(user.id, "user.undo_to", {
        "diagram_id": str(diagram_id),
        "draft_id": str(draft_id) if draft_id else None,
        "applied": res.applied,
        "cursor_seq": res.cursor_seq,
    })
    _broadcast_diagram_refetch(diagram_id, draft_id, "undo_to")
    return UndoToResponse(applied=res.applied, cursor_seq=res.cursor_seq)
