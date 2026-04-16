import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import Flow
from app.schemas.flow import FlowCreate, FlowUpdate


async def list_flows(db: AsyncSession, diagram_id: uuid.UUID) -> list[Flow]:
    result = await db.execute(
        select(Flow)
        .where(Flow.diagram_id == diagram_id)
        .order_by(Flow.created_at.asc())
    )
    return list(result.scalars().all())


async def get_flow(db: AsyncSession, flow_id: uuid.UUID) -> Flow | None:
    result = await db.execute(select(Flow).where(Flow.id == flow_id))
    return result.scalar_one_or_none()


async def create_flow(
    db: AsyncSession, diagram_id: uuid.UUID, data: FlowCreate
) -> Flow:
    flow = Flow(
        diagram_id=diagram_id,
        name=data.name,
        description=data.description,
        steps=[s.model_dump(mode="json") for s in data.steps],
    )
    db.add(flow)
    await db.flush()
    await db.refresh(flow)
    return flow


async def update_flow(db: AsyncSession, flow: Flow, data: FlowUpdate) -> Flow:
    update = data.model_dump(exclude_unset=True)
    if "steps" in update and update["steps"] is not None:
        update["steps"] = [s.model_dump(mode="json") if hasattr(s, "model_dump") else s for s in update["steps"]]
    for field, value in update.items():
        setattr(flow, field, value)
    await db.flush()
    await db.refresh(flow)
    return flow


async def delete_flow(db: AsyncSession, flow: Flow) -> None:
    await db.delete(flow)
    await db.flush()
