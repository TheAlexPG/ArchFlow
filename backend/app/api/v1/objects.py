import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.object import ObjectCreate, ObjectResponse, ObjectUpdate
from app.services import object_service

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("", response_model=list[ObjectResponse])
async def list_objects(
    type: str | None = Query(None),
    status: str | None = Query(None),
    parent_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    objects = await object_service.get_objects(db, type, status, parent_id)
    return [ObjectResponse.from_model(obj) for obj in objects]


@router.get("/{object_id}", response_model=ObjectResponse)
async def get_object(object_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    obj = await object_service.get_object(db, object_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")
    return ObjectResponse.from_model(obj)


@router.post("", response_model=ObjectResponse, status_code=201)
async def create_object(data: ObjectCreate, db: AsyncSession = Depends(get_db)):
    if data.parent_id:
        parent = await object_service.get_object(db, data.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent object not found")
    obj = await object_service.create_object(db, data)
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
