import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.activity_log import ActivityTargetType
from app.schemas.activity import ActivityLogResponse
from app.schemas.diagram import DiagramResponse
from app.schemas.object import ObjectCreate, ObjectResponse, ObjectUpdate
from app.services import activity_service, ai_service, diagram_service, object_service

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
):
    objects = await object_service.get_objects(
        db, type, status, parent_id, draft_id=draft_id
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
):
    if data.parent_id:
        parent = await object_service.get_object(db, data.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent object not found")
    obj = await object_service.create_object(db, data, draft_id=draft_id)
    return ObjectResponse.from_model(obj)


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
    return ObjectResponse.from_model(obj)


@router.delete("/{object_id}", status_code=204)
async def delete_object(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    await object_service.delete_object(db, obj)


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
