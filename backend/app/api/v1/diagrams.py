import uuid

from fastapi import APIRouter, Depends, HTTPException
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
from app.services import diagram_service

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("", response_model=list[DiagramResponse])
async def list_diagrams(db: AsyncSession = Depends(get_db)):
    return await diagram_service.get_diagrams(db)


@router.get("/{diagram_id}", response_model=DiagramResponse)
async def get_diagram(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return diagram


@router.post("", response_model=DiagramResponse, status_code=201)
async def create_diagram(
    data: DiagramCreate, db: AsyncSession = Depends(get_db)
):
    return await diagram_service.create_diagram(db, data)


@router.put("/{diagram_id}", response_model=DiagramResponse)
async def update_diagram(
    diagram_id: uuid.UUID,
    data: DiagramUpdate,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return await diagram_service.update_diagram(db, diagram, data)


@router.delete("/{diagram_id}", status_code=204)
async def delete_diagram(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    await diagram_service.delete_diagram(db, diagram)


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
