import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagram import Diagram
from app.models.pack import DiagramPack


async def create_pack(db: AsyncSession, workspace_id: uuid.UUID, name: str) -> DiagramPack:
    pack = DiagramPack(workspace_id=workspace_id, name=name)
    db.add(pack)
    await db.commit()
    await db.refresh(pack)
    return pack


async def list_packs(db: AsyncSession, workspace_id: uuid.UUID) -> list[DiagramPack]:
    result = await db.execute(
        select(DiagramPack)
        .where(DiagramPack.workspace_id == workspace_id)
        .order_by(DiagramPack.sort_order, DiagramPack.created_at)
    )
    return list(result.scalars().all())


async def get_pack(
    db: AsyncSession, workspace_id: uuid.UUID, pack_id: uuid.UUID
) -> DiagramPack | None:
    result = await db.execute(
        select(DiagramPack).where(
            DiagramPack.id == pack_id,
            DiagramPack.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def rename_pack(db: AsyncSession, pack: DiagramPack, name: str) -> DiagramPack:
    pack.name = name  # type: ignore[assignment]
    await db.commit()
    await db.refresh(pack)
    return pack


async def update_pack(
    db: AsyncSession, pack: DiagramPack, name: str | None, sort_order: int | None
) -> DiagramPack:
    if name is not None:
        pack.name = name  # type: ignore[assignment]
    if sort_order is not None:
        pack.sort_order = sort_order  # type: ignore[assignment]
    await db.commit()
    await db.refresh(pack)
    return pack


async def delete_pack(db: AsyncSession, pack: DiagramPack) -> None:
    await db.delete(pack)
    await db.commit()


async def reorder_packs(
    db: AsyncSession, workspace_id: uuid.UUID, ordered_ids: list[uuid.UUID]
) -> None:
    for idx, pack_id in enumerate(ordered_ids):
        await db.execute(
            update(DiagramPack)
            .where(DiagramPack.id == pack_id, DiagramPack.workspace_id == workspace_id)
            .values(sort_order=idx)
        )
    await db.commit()


async def set_diagram_pack(
    db: AsyncSession, diagram: Diagram, pack_id: uuid.UUID | None
) -> Diagram:
    diagram.pack_id = pack_id  # type: ignore[assignment]
    await db.commit()
    await db.refresh(diagram)
    return diagram
