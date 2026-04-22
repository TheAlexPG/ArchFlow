import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
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
from app.api.deps import get_current_workspace_id, get_optional_user
from app.realtime.manager import (
    fire_and_forget_publish,
    fire_and_forget_publish_diagram,
)
from app.services import access_service, diagram_service, draft_service, workspace_service
from app.services import pack_service
from app.services.webhook_service import fire_and_forget_emit

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("", response_model=list[DiagramResponse])
async def list_diagrams(
    scope_object_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
    workspace_id: uuid.UUID | None = Depends(get_current_workspace_id),
):
    """
    Authenticated callers see only the diagrams in the workspace they're
    currently operating in (X-Workspace-ID header, falling back to their
    default workspace). Team-ACL is then applied on top for non-admins.
    Unauthenticated callers still see everything for now — full auth
    rollout is a follow-up.
    """
    if current_user is None:
        return await diagram_service.get_diagrams(db, scope_object_id)
    if workspace_id is None:
        # Authenticated user with no workspace yet — show nothing rather
        # than leaking other callers' diagrams.
        return []
    diagrams = await diagram_service.get_diagrams(
        db, scope_object_id, workspace_id=workspace_id
    )
    membership = await workspace_service.get_user_membership(
        db, current_user.id, workspace_id
    )
    if membership is None:
        return []
    allowed = await access_service.filter_visible_diagram_ids(
        db, current_user.id, workspace_id, membership.role
    )
    if allowed is None:
        return diagrams
    return [d for d in diagrams if d.id in allowed]


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
    data: DiagramCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
):
    workspace_id = None
    if current_user is not None:
        # Prefer the explicit X-Workspace-ID header so the diagram is
        # stamped with the workspace the user is actually looking at;
        # fall back to their oldest workspace if the header is missing.
        if x_workspace_id:
            try:
                candidate = uuid.UUID(x_workspace_id)
            except ValueError:
                candidate = None
            if candidate is not None and await workspace_service.get_user_membership(
                db, current_user.id, candidate
            ):
                workspace_id = candidate
        if workspace_id is None:
            ws = await workspace_service.get_default_workspace_for_user(
                db, current_user.id
            )
            if ws is not None:
                workspace_id = ws.id
    diagram = await diagram_service.create_diagram(db, data, workspace_id=workspace_id)
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
    obj = await diagram_service.add_object_to_diagram(db, diagram_id, data)
    body = DiagramObjectResponse.model_validate(obj).model_dump(mode="json")
    payload = {"diagram_id": str(diagram_id), "diagram_object": body}
    fire_and_forget_publish(
        getattr(diagram, "workspace_id", None),
        "diagram_object.added",
        payload,
    )
    fire_and_forget_publish_diagram(diagram_id, "diagram_object.added", payload)
    return obj


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
    diagram = await diagram_service.get_diagram(db, diagram_id)
    body = DiagramObjectResponse.model_validate(obj).model_dump(mode="json")
    payload = {"diagram_id": str(diagram_id), "diagram_object": body}
    fire_and_forget_publish(
        getattr(diagram, "workspace_id", None) if diagram else None,
        "diagram_object.updated",
        payload,
    )
    fire_and_forget_publish_diagram(diagram_id, "diagram_object.updated", payload)
    return obj


@router.delete("/{diagram_id}/objects/{object_id}", status_code=204)
async def remove_object_from_diagram(
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    removed = await diagram_service.remove_object_from_diagram(
        db, diagram_id, object_id
    )
    if not removed:
        raise HTTPException(
            status_code=404, detail="Object not found in diagram"
        )
    payload = {"diagram_id": str(diagram_id), "object_id": str(object_id)}
    fire_and_forget_publish(
        getattr(diagram, "workspace_id", None) if diagram else None,
        "diagram_object.removed",
        payload,
    )
    fire_and_forget_publish_diagram(
        diagram_id, "diagram_object.removed", payload
    )


# ─── Pack assignment ──────────────────────────────────────────

class SetDiagramPackBody(BaseModel):
    pack_id: uuid.UUID | None


@router.put("/{diagram_id}/pack", response_model=DiagramResponse)
async def set_diagram_pack(
    diagram_id: uuid.UUID,
    body: SetDiagramPackBody,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    if body.pack_id is not None:
        # Verify the pack belongs to the same workspace as the diagram.
        pack = await pack_service.get_pack(db, diagram.workspace_id, body.pack_id)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail="Pack not found in this diagram's workspace",
            )
    diagram = await pack_service.set_diagram_pack(db, diagram, body.pack_id)
    return diagram


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
