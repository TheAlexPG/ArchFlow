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
# user-visible state, so showing them in the history tab is noise. Covers
# both SQL column names and the Python attribute names (ModelObject uses
# `metadata_` as the attribute for a column whose SQL name is "metadata",
# to avoid colliding with SQLAlchemy's reserved `Base.metadata`).
_IGNORED_DIFF_FIELDS = {"id", "created_at", "updated_at", "metadata", "metadata_"}


def _snapshot(obj: Any) -> dict:
    """Pick the user-visible attributes off an ORM row for a change diff."""
    if obj is None:
        return {}
    result = {}
    for col in obj.__table__.columns:
        # Read via the Python attribute name (`col.key`), not the SQL
        # column name — otherwise columns renamed at mapping time (e.g.
        # `metadata_` → SQL `metadata`) would shadow `Base.metadata`
        # and we'd try to JSON-serialize a SQLAlchemy MetaData instance.
        attr_name = col.key
        sql_name = col.name
        if attr_name in _IGNORED_DIFF_FIELDS or sql_name in _IGNORED_DIFF_FIELDS:
            continue
        value = getattr(obj, attr_name, None)
        result[attr_name] = _to_jsonable(value)
    return result


def _to_jsonable(value: Any) -> Any:
    """Coerce a column value into something JSON-safe for JSONB storage."""
    if hasattr(value, "value") and not isinstance(value, (list, tuple, dict)):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


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
    workspace_id: uuid.UUID | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        target_type=target_type,
        target_id=obj.id,
        action=ActivityAction.CREATED,
        changes=_snapshot(obj),
        user_id=user_id,
        workspace_id=workspace_id,
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
    workspace_id: uuid.UUID | None = None,
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
        workspace_id=workspace_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def log_deleted(
    db: AsyncSession,
    target_type: ActivityTargetType,
    obj: Any,
    user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        target_type=target_type,
        target_id=obj.id,
        action=ActivityAction.DELETED,
        changes=_snapshot(obj),
        user_id=user_id,
        workspace_id=workspace_id,
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
