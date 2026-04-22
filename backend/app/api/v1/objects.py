import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_optional_user
from app.core.database import get_db
from app.models.activity_log import ActivityTargetType
from app.schemas.activity import ActivityLogResponse
from app.schemas.diagram import DiagramResponse
from app.schemas.object import ObjectCreate, ObjectResponse, ObjectUpdate
from app.services import (
    activity_service,
    ai_service,
    diagram_service,
    object_service,
    workspace_service,
)
from app.realtime.manager import (
    fire_and_forget_publish,
    fire_and_forget_publish_diagram,
)
from app.services.webhook_service import fire_and_forget_emit

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("", response_model=list[ObjectResponse])
async def list_objects(
    type: str | None = Query(None),
    status: str | None = Query(None),
    parent_id: uuid.UUID | None = Query(None),
    draft_id: uuid.UUID | None = Query(
        None,
        description="When set, also include ModelObjects scoped to this draft "
        "(forked clones). Otherwise only live objects are returned.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
    workspace_id: uuid.UUID | None = Depends(get_current_workspace_id),
):
    # Authenticated callers are scoped to their current workspace so switching
    # workspaces doesn't leak objects from another one. Unauthenticated
    # callers still see everything (matches legacy behaviour).
    effective_workspace_id = workspace_id if current_user is not None else None
    if current_user is not None and effective_workspace_id is None:
        return []
    objects = await object_service.get_objects(
        db, type, status, parent_id, draft_id=draft_id,
        workspace_id=effective_workspace_id,
    )
    return [ObjectResponse.from_model(obj) for obj in objects]


@router.get("/{object_id}", response_model=ObjectResponse)
async def get_object(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    return ObjectResponse.from_model(obj)


@router.post("", response_model=ObjectResponse, status_code=201)
async def create_object(
    data: ObjectCreate,
    draft_id: uuid.UUID | None = Query(
        None, description="If set, the new object is scoped to this draft."
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_optional_user),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
):
    if data.parent_id:
        parent = await object_service.get_object(db, data.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent object not found")
    workspace_id: uuid.UUID | None = None
    if current_user is not None:
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
    obj = await object_service.create_object(
        db, data, draft_id=draft_id, workspace_id=workspace_id
    )
    response = ObjectResponse.from_model(obj)
    if draft_id is None:
        body = response.model_dump(mode="json")
        fire_and_forget_emit("object.created", body)
        fire_and_forget_publish(
            getattr(obj, "workspace_id", None), "object.created", {"object": body}
        )
    return response


async def _fanout_object_to_diagrams(
    db: AsyncSession, object_id: uuid.UUID, event_type: str, payload: dict
) -> None:
    diagrams = await diagram_service.get_diagrams_containing_object(db, object_id)
    for d in diagrams:
        fire_and_forget_publish_diagram(d.id, event_type, payload)


@router.put("/{object_id}", response_model=ObjectResponse)
async def update_object(
    object_id: uuid.UUID,
    data: ObjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    obj = await object_service.update_object(db, obj, data)
    response = ObjectResponse.from_model(obj)
    if obj.draft_id is None:
        body = response.model_dump(mode="json")
        fire_and_forget_emit("object.updated", body)
        fire_and_forget_publish(
            getattr(obj, "workspace_id", None), "object.updated", {"object": body}
        )
        await _fanout_object_to_diagrams(
            db, obj.id, "object.updated", {"object": body}
        )
    return response


@router.delete("/{object_id}", status_code=204)
async def delete_object(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    was_draft = obj.draft_id is not None
    obj_id_str = str(obj.id)
    obj_ws_id = getattr(obj, "workspace_id", None)
    # Capture the containing diagrams BEFORE the delete so we still know
    # where to fan out the event; the junction rows go away with the object.
    diagrams_before = (
        await diagram_service.get_diagrams_containing_object(db, obj.id)
        if not was_draft
        else []
    )
    await object_service.delete_object(db, obj)
    if not was_draft:
        fire_and_forget_emit("object.deleted", {"id": obj_id_str})
        fire_and_forget_publish(obj_ws_id, "object.deleted", {"id": obj_id_str})
        for d in diagrams_before:
            fire_and_forget_publish_diagram(
                d.id, "object.deleted", {"id": obj_id_str}
            )


@router.get("/{object_id}/children", response_model=list[ObjectResponse])
async def get_children(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    children = await object_service.get_children(db, object_id)
    return [ObjectResponse.from_model(c) for c in children]


@router.get("/{object_id}/diagrams", response_model=list[DiagramResponse])
async def get_object_diagrams(
    object_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    return await diagram_service.get_diagrams_containing_object(db, object_id)


@router.get(
    "/{object_id}/history",
    response_model=list[ActivityLogResponse],
)
async def get_object_history(
    object_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    entries = await activity_service.get_history(
        db, ActivityTargetType.OBJECT, object_id, limit=limit
    )
    return [ActivityLogResponse.model_validate(e) for e in entries]


@router.post("/{object_id}/insights")
async def get_object_insights(
    object_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    if not ai_service.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "AI features are disabled. Set ANTHROPIC_API_KEY in the backend "
                "environment to enable Get insights."
            ),
        )
    try:
        return await ai_service.get_insights(db, object_id)
    except Exception as e:  # noqa: BLE001 — surface upstream errors to the UI
        raise HTTPException(status_code=502, detail=f"AI call failed: {e}") from e


@router.get("/{object_id}/dependencies")
async def get_dependencies(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    deps = await object_service.get_dependencies(db, object_id)
    return {
        "upstream": [
            {"connection_id": c.id, "source": ObjectResponse.from_model(c.source).model_dump()}
            for c in deps["upstream"]
        ],
        "downstream": [
            {"connection_id": c.id, "target": ObjectResponse.from_model(c.target).model_dump()}
            for c in deps["downstream"]
        ],
    }
