import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.diagram import (
    DiagramCreate,
    DiagramObjectCreate,
    DiagramObjectResponse,
    DiagramObjectUpdate,
    DiagramResponse,
    DiagramUpdate,
)
from app.api.deps import get_optional_user
from app.realtime.manager import fire_and_forget_publish
from app.services import access_service, diagram_service, draft_service, workspace_service
from app.services.webhook_service import fire_and_forget_emit

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("", response_model=list[DiagramResponse])
async def list_diagrams(
    scope_object_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    """
    When the caller is authenticated and has a workspace, restrict the list
    to diagrams they have team-granted access to. Workspace admins+ see
    everything. Unauthenticated callers still see everything for now — full
    auth rollout is a follow-up.
    """
    diagrams = await diagram_service.get_diagrams(db, scope_object_id)
    if current_user is None:
        return diagrams
    workspace = await workspace_service.get_default_workspace_for_user(
        db, current_user.id
    )
    if workspace is None:
        return diagrams
    membership = await workspace_service.get_user_membership(
        db, current_user.id, workspace.id
    )
    if membership is None:
        return diagrams
    allowed = await access_service.filter_visible_diagram_ids(
        db, current_user.id, workspace.id, membership.role
    )
    if allowed is None:
        return diagrams
    return [d for d in diagrams if d.id in allowed or d.workspace_id != workspace.id]


@router.get("/{diagram_id}", response_model=DiagramResponse)
async def get_diagram(
    diagram_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    # If the diagram is scoped to a workspace AND the caller is an
    # authenticated member of that workspace, enforce team ACL.
    if current_user is not None and diagram.workspace_id is not None:
        membership = await workspace_service.get_user_membership(
            db, current_user.id, diagram.workspace_id
        )
        if membership is not None and not await access_service.can_read_diagram(
            db, current_user.id, diagram, membership.role
        ):
            raise HTTPException(status_code=403, detail="No access to this diagram")
    return diagram


@router.post("", response_model=DiagramResponse, status_code=201)
async def create_diagram(
    data: DiagramCreate, db: AsyncSession = Depends(get_db)
):
    diagram = await diagram_service.create_diagram(db, data)
    body = DiagramResponse.model_validate(diagram).model_dump(mode="json")
    fire_and_forget_emit("diagram.created", body)
    fire_and_forget_publish(
        getattr(diagram, "workspace_id", None), "diagram.created", {"diagram": body}
    )
    return diagram


@router.put("/{diagram_id}", response_model=DiagramResponse)
async def update_diagram(
    diagram_id: uuid.UUID,
    data: DiagramUpdate,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    diagram = await diagram_service.update_diagram(db, diagram, data)
    body = DiagramResponse.model_validate(diagram).model_dump(mode="json")
    fire_and_forget_emit("diagram.updated", body)
    fire_and_forget_publish(
        getattr(diagram, "workspace_id", None), "diagram.updated", {"diagram": body}
    )
    return diagram


@router.delete("/{diagram_id}", status_code=204)
async def delete_diagram(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    diagram_id_str = str(diagram.id)
    diagram_ws_id = getattr(diagram, "workspace_id", None)
    await diagram_service.delete_diagram(db, diagram)
    fire_and_forget_emit("diagram.deleted", {"id": diagram_id_str})
    fire_and_forget_publish(diagram_ws_id, "diagram.deleted", {"id": diagram_id_str})


# ─── Diagram Objects (positions per diagram) ─────────────

@router.get(
    "/{diagram_id}/objects", response_model=list[DiagramObjectResponse]
)
async def list_diagram_objects(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    return await diagram_service.get_diagram_objects(db, diagram_id)


@router.post(
    "/{diagram_id}/objects",
    response_model=DiagramObjectResponse,
    status_code=201,
)
async def add_object_to_diagram(
    diagram_id: uuid.UUID,
    data: DiagramObjectCreate,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return await diagram_service.add_object_to_diagram(db, diagram_id, data)


@router.put(
    "/{diagram_id}/objects/{object_id}",
    response_model=DiagramObjectResponse,
)
async def update_diagram_object(
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    data: DiagramObjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    obj = await diagram_service.update_diagram_object(
        db, diagram_id, object_id, data
    )
    if not obj:
        raise HTTPException(
            status_code=404, detail="Object not found in diagram"
        )
    return obj


@router.delete("/{diagram_id}/objects/{object_id}", status_code=204)
async def remove_object_from_diagram(
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    removed = await diagram_service.remove_object_from_diagram(
        db, diagram_id, object_id
    )
    if not removed:
        raise HTTPException(
            status_code=404, detail="Object not found in diagram"
        )


# ─── Draft membership ─────────────────────────────────────────

@router.get("/{diagram_id}/drafts")
async def get_diagram_drafts(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    """Return all OPEN drafts that include this diagram as a source.

    Each entry has draft_id, draft_name, source_diagram_id, and
    forked_diagram_id so the frontend can navigate directly to the fork.
    """
    return await draft_service.get_drafts_for_diagram(db, diagram_id)
