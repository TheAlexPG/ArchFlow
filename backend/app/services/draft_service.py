import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.draft import Draft, DraftItem, DraftStatus
from app.models.object import ModelObject
from app.schemas.draft import DraftCreate, DraftItemCreate, DraftItemUpdate, DraftUpdate
from app.services import activity_service


# Fields we snapshot / allow editing via a DraftItem.
_OBJECT_FIELDS = {
    "name",
    "type",
    "scope",
    "status",
    "description",
    "icon",
    "parent_id",
    "technology",
    "tags",
    "owner_team",
    "external_links",
}


def _snapshot_object(obj: ModelObject) -> dict:
    """Serialize the editable fields of a ModelObject for diff/apply."""
    data = {}
    for field in _OBJECT_FIELDS:
        value = getattr(obj, field, None)
        if hasattr(value, "value"):
            value = value.value
        elif isinstance(value, uuid.UUID):
            value = str(value)
        data[field] = value
    return data


async def list_drafts(db: AsyncSession) -> list[Draft]:
    result = await db.execute(
        select(Draft)
        .options(selectinload(Draft.items))
        .order_by(Draft.created_at.desc())
    )
    return list(result.scalars().all())


async def get_draft(db: AsyncSession, draft_id: uuid.UUID) -> Draft | None:
    result = await db.execute(
        select(Draft)
        .where(Draft.id == draft_id)
        .options(selectinload(Draft.items))
    )
    return result.scalar_one_or_none()


async def create_draft(
    db: AsyncSession, data: DraftCreate, author_id: uuid.UUID | None = None
) -> Draft:
    draft = Draft(name=data.name, description=data.description, author_id=author_id)
    db.add(draft)
    await db.flush()
    await db.refresh(draft, attribute_names=["items"])
    return draft


async def update_draft(db: AsyncSession, draft: Draft, data: DraftUpdate) -> Draft:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(draft, field, value)
    await db.flush()
    await db.refresh(draft, attribute_names=["items"])
    return draft


async def delete_draft(db: AsyncSession, draft: Draft) -> None:
    await db.delete(draft)
    await db.flush()


async def add_item(
    db: AsyncSession, draft: Draft, data: DraftItemCreate
) -> DraftItem:
    """Add (or replace) a draft item for a target object.

    If target_id is set and already has a DraftItem in this draft, updates
    its proposed_state and returns the existing item — one edit per object
    per draft keeps the diff simple.
    """
    baseline = None
    if data.target_id:
        obj = await db.get(ModelObject, data.target_id)
        if obj:
            baseline = _snapshot_object(obj)
        # Check for an existing item
        existing = next(
            (i for i in draft.items if i.target_id == data.target_id), None
        )
        if existing:
            existing.proposed_state = data.proposed_state
            existing.baseline = baseline
            await db.flush()
            return existing

    item = DraftItem(
        draft_id=draft.id,
        target_type=data.target_type,
        target_id=data.target_id,
        baseline=baseline,
        proposed_state=data.proposed_state,
    )
    db.add(item)
    await db.flush()
    return item


async def update_item(
    db: AsyncSession, item: DraftItem, data: DraftItemUpdate
) -> DraftItem:
    item.proposed_state = data.proposed_state
    await db.flush()
    return item


async def delete_item(db: AsyncSession, item: DraftItem) -> None:
    await db.delete(item)
    await db.flush()


async def apply_draft(db: AsyncSession, draft: Draft) -> dict:
    """Apply every DraftItem to the live model, mark the draft merged.

    For existing objects (target_id set) we mutate in place. For new
    objects (target_id null) we create one and return its id in the
    summary so callers can refresh.
    """
    if draft.status != DraftStatus.OPEN:
        raise ValueError(f"Draft is {draft.status.value}, cannot apply")

    applied_updates = 0
    created_ids: list[str] = []

    for item in draft.items:
        if item.target_type != "object":
            continue
        proposed = item.proposed_state or {}
        if item.target_id:
            obj = await db.get(ModelObject, item.target_id)
            if not obj:
                continue
            before = activity_service.snapshot(obj)
            for field in _OBJECT_FIELDS:
                if field in proposed:
                    setattr(obj, field, proposed[field])
            await db.flush()
            after = activity_service.snapshot(obj)
            from app.models.activity_log import ActivityTargetType

            await activity_service.log_updated(
                db, ActivityTargetType.OBJECT, obj.id, before, after
            )
            applied_updates += 1
        else:
            obj = ModelObject(**{k: v for k, v in proposed.items() if k in _OBJECT_FIELDS})
            db.add(obj)
            await db.flush()
            created_ids.append(str(obj.id))
            from app.models.activity_log import ActivityTargetType

            await activity_service.log_created(db, ActivityTargetType.OBJECT, obj)

    draft.status = DraftStatus.MERGED
    await db.flush()

    return {
        "draft_id": str(draft.id),
        "status": draft.status.value,
        "updated": applied_updates,
        "created_ids": created_ids,
    }


async def discard_draft(db: AsyncSession, draft: Draft) -> Draft:
    draft.status = DraftStatus.DISCARDED
    await db.flush()
    return draft


async def snapshot_object(db: AsyncSession, object_id: uuid.UUID) -> dict | None:
    obj = await db.get(ModelObject, object_id)
    if not obj:
        return None
    return _snapshot_object(obj)
