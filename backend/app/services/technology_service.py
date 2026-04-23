"""Technology catalog service.

Reads built-in and custom technologies, manages custom (workspace-scoped)
mutations, and enforces reference integrity on delete. Built-in rows
(workspace_id IS NULL) are read-only at runtime — they are only written by
the seed migration.
"""
import re
import uuid

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityTargetType
from app.models.technology import TechCategory, Technology
from app.schemas.technology import TechnologyCreate, TechnologyUpdate
from app.services import activity_service

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Deterministic slug from a display name. Empty result → 'tech'."""
    collapsed = _SLUG_STRIP.sub("-", name.lower()).strip("-")
    return collapsed or "tech"


async def _slug_is_free(
    db: AsyncSession, workspace_id: uuid.UUID, slug: str
) -> bool:
    result = await db.execute(
        select(Technology.id).where(
            Technology.workspace_id == workspace_id,
            Technology.slug == slug,
        )
    )
    return result.first() is None


async def _unique_slug(
    db: AsyncSession, workspace_id: uuid.UUID, base: str
) -> str:
    if await _slug_is_free(db, workspace_id, base):
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if await _slug_is_free(db, workspace_id, candidate):
            return candidate
    raise RuntimeError("could not generate a unique slug")


async def list_technologies(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    q: str | None = None,
    category: TechCategory | None = None,
    scope: str = "all",
) -> list[Technology]:
    """Return built-in + this workspace's custom, filtered by q/category/scope."""
    stmt = select(Technology)

    if scope == "builtin":
        stmt = stmt.where(Technology.workspace_id.is_(None))
    elif scope == "custom":
        stmt = stmt.where(Technology.workspace_id == workspace_id)
    else:
        stmt = stmt.where(
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            )
        )

    if category is not None:
        stmt = stmt.where(Technology.category == category)

    if q:
        term = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Technology.name).ilike(term),
                func.lower(Technology.slug).ilike(term),
                # aliases is TEXT[] — EXISTS over unnest with ILIKE
                text(
                    "EXISTS (SELECT 1 FROM unnest(technologies.aliases) AS a "
                    "WHERE LOWER(a) LIKE :qterm)"
                ).bindparams(qterm=term),
            )
        )

    stmt = stmt.order_by(Technology.category, Technology.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_technology(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    technology_id: uuid.UUID,
) -> Technology | None:
    """Return a technology if it's a built-in or belongs to this workspace."""
    result = await db.execute(
        select(Technology).where(
            Technology.id == technology_id,
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            ),
        )
    )
    return result.scalar_one_or_none()


async def create_custom(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    payload: TechnologyCreate,
    user_id: uuid.UUID | None,
) -> Technology:
    slug = payload.slug or slugify(payload.name)
    slug = await _unique_slug(db, workspace_id, slug)

    tech = Technology(
        workspace_id=workspace_id,
        slug=slug,
        name=payload.name,
        iconify_name=payload.iconify_name,
        category=payload.category,
        color=payload.color,
        aliases=payload.aliases,
        created_by_user_id=user_id,
    )
    db.add(tech)
    await db.flush()
    await activity_service.log_created(
        db, ActivityTargetType.TECHNOLOGY, tech, user_id=user_id
    )
    await db.commit()
    await db.refresh(tech)
    return tech


async def update_custom(
    db: AsyncSession,
    tech: Technology,
    payload: TechnologyUpdate,
    user_id: uuid.UUID | None,
) -> Technology:
    if tech.workspace_id is None:
        raise ValueError("Built-in technologies are read-only")

    before = activity_service.snapshot(tech)

    if payload.name is not None:
        tech.name = payload.name  # type: ignore[assignment]
    if payload.iconify_name is not None:
        tech.iconify_name = payload.iconify_name  # type: ignore[assignment]
    if payload.category is not None:
        tech.category = payload.category  # type: ignore[assignment]
    if payload.color is not None:
        tech.color = payload.color  # type: ignore[assignment]
    if payload.aliases is not None:
        tech.aliases = payload.aliases  # type: ignore[assignment]

    await db.flush()
    after = activity_service.snapshot(tech)
    await activity_service.log_updated(
        db,
        ActivityTargetType.TECHNOLOGY,
        tech.id,
        before,
        after,
        user_id=user_id,
    )
    await db.commit()
    await db.refresh(tech)
    return tech


async def count_references(
    db: AsyncSession, technology_id: uuid.UUID
) -> tuple[int, int]:
    """How many objects / connections reference this technology.

    Uses raw SQL against the post-M3 schema columns (`technology_ids`,
    `protocol_id`). Works once the M3 migrations have been applied; until
    then delete is unreachable from the live API anyway because the feature
    needs the full chain to be deployed together.
    """
    object_count = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM model_objects "
                "WHERE :id = ANY(technology_ids)"
            ).bindparams(id=technology_id)
        )
    ).scalar_one()

    connection_count = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM connections WHERE protocol_id = :id"
            ).bindparams(id=technology_id)
        )
    ).scalar_one()

    return int(object_count or 0), int(connection_count or 0)


async def delete_custom(
    db: AsyncSession,
    tech: Technology,
    user_id: uuid.UUID | None,
) -> tuple[int, int] | None:
    """Delete a custom technology.

    Returns (object_refs, connection_refs) if deletion is blocked by
    references, otherwise None and the row is deleted.
    """
    if tech.workspace_id is None:
        raise ValueError("Built-in technologies are read-only")

    obj_refs, conn_refs = await count_references(db, tech.id)
    if obj_refs or conn_refs:
        return obj_refs, conn_refs

    await activity_service.log_deleted(
        db, ActivityTargetType.TECHNOLOGY, tech, user_id=user_id
    )
    await db.delete(tech)
    await db.commit()
    return None


# Silence unused-import warnings for types that callers may want — the
# ARRAY import documents that `aliases` travels as TEXT[].
__all__ = [
    "ARRAY",
    "count_references",
    "create_custom",
    "delete_custom",
    "get_technology",
    "list_technologies",
    "slugify",
    "update_custom",
]
