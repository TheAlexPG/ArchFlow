"""Restore deleted entities by reapplying a snapshot with the same UUID.

Used only by undo of delete actions. We do not call existing service
.create_*() functions because those allocate fresh UUIDs and we MUST
keep the original id so other diagrams referencing it still work.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import Comment
from app.models.connection import Connection
from app.models.diagram import DiagramObject
from app.models.object import ModelObject
from app.models.undo_entry import UndoTargetType


async def restore(
    db: AsyncSession,
    *,
    target_type: UndoTargetType,
    target_id: uuid.UUID,
    snapshot: dict,
) -> None:
    if target_type == UndoTargetType.OBJECT:
        await _restore_object(db, target_id, snapshot)
    elif target_type == UndoTargetType.CONNECTION:
        await _restore_connection(db, target_id, snapshot)
    elif target_type == UndoTargetType.DIAGRAM_OBJECT:
        await _restore_diagram_object(db, target_id, snapshot)
    elif target_type == UndoTargetType.COMMENT:
        await _restore_comment(db, target_id, snapshot)


def _materialise(model_cls, target_id: uuid.UUID, snapshot: dict):
    """Build a model instance with the original UUID + snapshot fields,
    skipping computed/virtual columns.

    Uses mapper attribute names (not raw SQL column names) so that columns
    renamed at mapping time (e.g. ``metadata_`` → SQL ``metadata``) are
    matched correctly — both spellings in the snapshot are accepted.
    """
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(model_cls)
    # Build a mapping from Python attr name → SQL column name for every
    # column attribute so we can accept either spelling from older snapshots.
    attr_names: set[str] = set()
    sql_to_attr: dict[str, str] = {}
    for col_attr in mapper.column_attrs:
        attr_names.add(col_attr.key)
        sql_to_attr[col_attr.columns[0].name] = col_attr.key

    payload: dict = {}
    for k, v in snapshot.items():
        if k.startswith("_"):
            continue  # _placements and other meta-keys
        if k in attr_names:
            payload[k] = v  # Python attr name — use directly
        elif k in sql_to_attr:
            payload[sql_to_attr[k]] = v  # SQL name — map to Python attr name
    payload["id"] = target_id
    return model_cls(**payload)


async def _restore_object(db, target_id, snapshot):
    db.add(_materialise(ModelObject, target_id, snapshot))
    for placement in snapshot.get("_placements", []):
        db.add(_materialise(DiagramObject, uuid.UUID(placement["id"]), placement))
    await db.flush()


async def _restore_connection(db, target_id, snapshot):
    db.add(_materialise(Connection, target_id, snapshot))
    await db.flush()


async def _restore_diagram_object(db, target_id, snapshot):
    db.add(_materialise(DiagramObject, target_id, snapshot))
    await db.flush()


async def _restore_comment(db, target_id, snapshot):
    db.add(_materialise(Comment, target_id, snapshot))
    await db.flush()
