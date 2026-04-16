import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.diagram import Diagram, DiagramObject
from app.schemas.diagram import (
    DiagramCreate,
    DiagramObjectCreate,
    DiagramObjectUpdate,
    DiagramUpdate,
)


async def get_diagrams(
    db: AsyncSession, scope_object_id: uuid.UUID | None = None
) -> list[Diagram]:
    query = select(Diagram)
    if scope_object_id is not None:
        query = query.where(Diagram.scope_object_id == scope_object_id)
    result = await db.execute(query.order_by(Diagram.name))
    return list(result.scalars().all())


async def get_diagram(db: AsyncSession, diagram_id: uuid.UUID) -> Diagram | None:
    result = await db.execute(
        select(Diagram)
        .where(Diagram.id == diagram_id)
        .options(selectinload(Diagram.objects))
    )
    return result.scalar_one_or_none()


async def create_diagram(db: AsyncSession, data: DiagramCreate) -> Diagram:
    diagram = Diagram(
        name=data.name,
        type=data.type,
        description=data.description,
        scope_object_id=data.scope_object_id,
        settings=data.settings,
    )
    db.add(diagram)
    await db.flush()
    await db.refresh(diagram)
    return diagram


async def update_diagram(
    db: AsyncSession, diagram: Diagram, data: DiagramUpdate
) -> Diagram:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(diagram, field, value)
    await db.flush()
    await db.refresh(diagram)
    return diagram


async def delete_diagram(db: AsyncSession, diagram: Diagram) -> None:
    await db.delete(diagram)
    await db.flush()


# ─── Diagram Objects (positions) ──────────────────────────

async def get_diagram_objects(
    db: AsyncSession, diagram_id: uuid.UUID
) -> list[DiagramObject]:
    result = await db.execute(
        select(DiagramObject).where(DiagramObject.diagram_id == diagram_id)
    )
    return list(result.scalars().all())


async def get_diagrams_containing_object(
    db: AsyncSession, object_id: uuid.UUID
) -> list[Diagram]:
    result = await db.execute(
        select(Diagram)
        .join(DiagramObject, DiagramObject.diagram_id == Diagram.id)
        .where(DiagramObject.object_id == object_id)
        .distinct()
    )
    return list(result.scalars().all())


async def add_object_to_diagram(
    db: AsyncSession, diagram_id: uuid.UUID, data: DiagramObjectCreate
) -> DiagramObject:
    obj = DiagramObject(
        diagram_id=diagram_id,
        object_id=data.object_id,
        position_x=data.position_x,
        position_y=data.position_y,
        width=data.width,
        height=data.height,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def update_diagram_object(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    object_id: uuid.UUID,
    data: DiagramObjectUpdate,
) -> DiagramObject | None:
    result = await db.execute(
        select(DiagramObject).where(
            DiagramObject.diagram_id == diagram_id,
            DiagramObject.object_id == object_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(obj, field, value)
    await db.flush()
    await db.refresh(obj)
    return obj


async def remove_object_from_diagram(
    db: AsyncSession, diagram_id: uuid.UUID, object_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(DiagramObject).where(
            DiagramObject.diagram_id == diagram_id,
            DiagramObject.object_id == object_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        return False
    await db.delete(obj)
    await db.flush()
    return True
