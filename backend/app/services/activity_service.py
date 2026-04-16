"""Activity log service.

Records append-only events for objects/connections/diagrams, and queries
back history for the per-object sidebar History tab.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityAction, ActivityLog, ActivityTargetType


# Fields we deliberately don't record as "changed" — they're bookkeeping, not
# user-visible state, so showing them in the history tab is noise.
_IGNORED_DIFF_FIELDS = {"id", "created_at", "updated_at"}


def _snapshot(obj: Any) -> dict:
    """Pick the user-visible attributes off an ORM row for a change diff."""
    if obj is None:
        return {}
    result = {}
    for col in obj.__table__.columns:
        name = col.name
        if name in _IGNORED_DIFF_FIELDS:
            continue
        value = getattr(obj, name, None)
        # enums → their string value; UUIDs → str; everything else is
        # already JSON-safe for JSONB (dicts/lists/primitives).
        if hasattr(value, "value"):
            value = value.value
        elif isinstance(value, uuid.UUID):
            value = str(value)
        result[name] = value
    return result


def diff_snapshots(before: dict, after: dict) -> dict:
    """Return {field: {before, after}} for fields that actually changed."""
    changes = {}
    for key in set(before) | set(after):
        b = before.get(key)
        a = after.get(key)
        if b != a:
            changes[key] = {"before": b, "after": a}
    return changes


async def log_created(
    db: AsyncSession,
    target_type: ActivityTargetType,
    obj: Any,
    user_id: uuid.UUID | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        target_type=target_type,
        target_id=obj.id,
        action=ActivityAction.CREATED,
        changes=_snapshot(obj),
        user_id=user_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def log_updated(
    db: AsyncSession,
    target_type: ActivityTargetType,
    target_id: uuid.UUID,
    before: dict,
    after: dict,
    user_id: uuid.UUID | None = None,
) -> ActivityLog | None:
    """Log an update only if there were actual changes."""
    changes = diff_snapshots(before, after)
    if not changes:
        return None
    entry = ActivityLog(
        target_type=target_type,
        target_id=target_id,
        action=ActivityAction.UPDATED,
        changes=changes,
        user_id=user_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def log_deleted(
    db: AsyncSession,
    target_type: ActivityTargetType,
    obj: Any,
    user_id: uuid.UUID | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        target_type=target_type,
        target_id=obj.id,
        action=ActivityAction.DELETED,
        changes=_snapshot(obj),
        user_id=user_id,
    )
    db.add(entry)
    await db.flush()
    return entry


def snapshot(obj: Any) -> dict:
    """Public helper so callers can capture `before` state for later diffing."""
    return _snapshot(obj)


async def get_history(
    db: AsyncSession,
    target_type: ActivityTargetType,
    target_id: uuid.UUID,
    limit: int = 100,
) -> list[ActivityLog]:
    result = await db.execute(
        select(ActivityLog)
        .where(
            ActivityLog.target_type == target_type,
            ActivityLog.target_id == target_id,
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
