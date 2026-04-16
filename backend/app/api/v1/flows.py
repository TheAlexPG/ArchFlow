import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.flow import FlowCreate, FlowResponse, FlowUpdate
from app.services import diagram_service, flow_service

router = APIRouter(prefix="/flows", tags=["flows"])
diagrams_router = APIRouter(prefix="/diagrams", tags=["flows"])


@diagrams_router.get(
    "/{diagram_id}/flows", response_model=list[FlowResponse]
)
async def list_flows(
    diagram_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return await flow_service.list_flows(db, diagram_id)


@diagrams_router.post(
    "/{diagram_id}/flows",
    response_model=FlowResponse,
    status_code=201,
)
async def create_flow(
    diagram_id: uuid.UUID,
    data: FlowCreate,
    db: AsyncSession = Depends(get_db),
):
    diagram = await diagram_service.get_diagram(db, diagram_id)
    if not diagram:
        raise HTTPException(status_code=404, detail="Diagram not found")
    return await flow_service.create_flow(db, diagram_id, data)


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(flow_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    flow = await flow_service.get_flow(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.put("/{flow_id}", response_model=FlowResponse)
async def update_flow(
    flow_id: uuid.UUID, data: FlowUpdate, db: AsyncSession = Depends(get_db)
):
    flow = await flow_service.get_flow(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return await flow_service.update_flow(db, flow, data)


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(flow_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    flow = await flow_service.get_flow(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    await flow_service.delete_flow(db, flow)
