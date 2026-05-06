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


def _snapshot(obj: Any, *, include_metadata: bool = False) -> dict:
    """Pick the user-visible attributes off an ORM row.

    By default `metadata_` (alias `metadata`) is excluded — the activity log's
    diff would be noisy if every metadata blob change rendered as a row.
    Pass `include_metadata=True` from undo recording sites where the snapshot
    must be sufficient to reconstruct the entity on undo of a delete, or to
    detect metadata-only edits.
    """
    if obj is None:
        return {}
    ignored = (
        _IGNORED_DIFF_FIELDS - {"metadata", "metadata_"}
        if include_metadata
        else _IGNORED_DIFF_FIELDS
    )
    from sqlalchemy import inspect as sa_inspect

    result = {}
    mapper = sa_inspect(type(obj))
    for col_attr in mapper.column_attrs:
        # col_attr.key is the *Python* attribute name (e.g. `metadata_`), which
        # may differ from the SQL column name (e.g. `metadata`).  Always use
        # the Python name so that `getattr(obj, attr_name)` returns the actual
        # column value, not a shadowing class attribute (e.g. Base.metadata).
        attr_name = col_attr.key
        # For filtering purposes also check the SQL column name so that callers
        # can pass either spelling in _IGNORED_DIFF_FIELDS.
        sql_name = col_attr.columns[0].name
        if attr_name in ignored or sql_name in ignored:
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


def snapshot(obj: Any, *, include_metadata: bool = False) -> dict:
    """Public helper so callers can capture `before` state for later diffing.

    Pass `include_metadata=True` from undo recording sites — the activity
    log's default keeps metadata out of audit diffs (it's blob churn), but
    undo needs the full row to reconstruct entities and detect metadata-only
    edits.
    """
    return _snapshot(obj, include_metadata=include_metadata)


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
