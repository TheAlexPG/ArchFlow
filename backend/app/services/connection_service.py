import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.object import ModelObject
from app.models.technology import Technology
from app.schemas.connection import ConnectionCreate, ConnectionUpdate
from app.services import activity_service


async def _validate_protocol_ids(
    db: AsyncSession,
    workspace_id: uuid.UUID | None,
    protocol_ids: list[uuid.UUID] | None,
) -> None:
    if not protocol_ids:
        return
    result = await db.execute(
        select(Technology.id).where(
            Technology.id.in_(protocol_ids),
            or_(
                Technology.workspace_id.is_(None),
                Technology.workspace_id == workspace_id,
            ),
        )
    )
    found = {row[0] for row in result.all()}
    missing = set(protocol_ids) - found
    if missing:
        raise ValueError(
            "Unknown or cross-workspace protocol_ids: "
            f"{sorted(str(m) for m in missing)}"
        )


async def _source_workspace_id(
    db: AsyncSession, source_id: uuid.UUID
) -> uuid.UUID | None:
    """The connection inherits its scope from the source object's workspace."""
    result = await db.execute(
        select(ModelObject.workspace_id).where(ModelObject.id == source_id)
    )
    return result.scalar_one_or_none()


async def get_connections(
    db: AsyncSession,
    draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> list[Connection]:
    query = select(Connection)
    if draft_id is not None:
        query = query.where(
            (Connection.draft_id.is_(None)) | (Connection.draft_id == draft_id)
        )
    else:
        query = query.where(Connection.draft_id.is_(None))
    if workspace_id is not None:
        # Connections don't carry their own workspace_id — scope them via the
        # source object's workspace so switching workspaces never leaks edges
        # from another workspace.
        query = query.where(
            Connection.source_id.in_(
                select(ModelObject.id).where(ModelObject.workspace_id == workspace_id)
            )
        )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_connection(db: AsyncSession, connection_id: uuid.UUID) -> Connection | None:
    result = await db.execute(select(Connection).where(Connection.id == connection_id))
    return result.scalar_one_or_none()


async def get_connections_between(
    db: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID
) -> list[Connection]:
    result = await db.execute(
        select(Connection).where(
            and_(Connection.source_id == source_id, Connection.target_id == target_id)
        )
    )
    return list(result.scalars().all())


async def create_connection(
    db: AsyncSession,
    data: ConnectionCreate,
    draft_id: uuid.UUID | None = None,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> Connection:
    ws_id = await _source_workspace_id(db, data.source_id)
    await _validate_protocol_ids(db, ws_id, data.protocol_ids)

    conn = Connection(
        source_id=data.source_id,
        target_id=data.target_id,
        label=data.label,
        protocol_ids=data.protocol_ids,
        direction=data.direction,
        tags=data.tags,
        source_handle=data.source_handle,
        target_handle=data.target_handle,
        shape=data.shape,
        label_size=data.label_size,
        via_object_ids=data.via_object_ids,
        draft_id=draft_id,
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)

    # Undo recording — only for live connections with full context
    if (
        actor_user is not None
        and from_diagram_id is not None
        and ws_id is not None
        and draft_id is None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=ws_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.CONNECTION,
            target_id=conn.id,
            action=UndoAction.CREATE,
            forward_summary=f"Created connection {str(conn.id)[:8]}"[:80],
            inverse_payload={"target_id": str(conn.id)},
            after_state=activity_service.snapshot(conn, include_metadata=True),
            coalesce_key=f"connection:{conn.id}:create",
        )

    return conn


async def update_connection(
    db: AsyncSession,
    conn: Connection,
    data: ConnectionUpdate,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> Connection:
    # Resolve once — used for both protocol validation and undo recording.
    ws_id = await _source_workspace_id(db, conn.source_id)

    if "protocol_ids" in data.model_fields_set:
        await _validate_protocol_ids(db, ws_id, data.protocol_ids)

    before = activity_service.snapshot(conn, include_metadata=True)
    update_data = data.model_dump(exclude_unset=True)
    # Strip undo-context fields that are not connection attributes
    update_data.pop("from_diagram_id", None)
    update_data.pop("from_draft_id", None)
    for field, value in update_data.items():
        setattr(conn, field, value)
    await db.flush()
    await db.refresh(conn)
    after = activity_service.snapshot(conn, include_metadata=True)

    # Undo recording
    if (
        actor_user is not None
        and from_diagram_id is not None
        and ws_id is not None
    ):
        diff = activity_service.diff_snapshots(before, after)
        if diff:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            await undo_service.record(
                db,
                user_id=actor_user.id,
                workspace_id=ws_id,
                diagram_id=from_diagram_id,
                draft_id=from_draft_id,
                target_type=UndoTargetType.CONNECTION,
                target_id=conn.id,
                action=UndoAction.UPDATE,
                forward_summary=_summarise_connection_diff(conn, diff),
                inverse_payload={"before": {k: v["before"] for k, v in diff.items()}},
                after_state={k: v["after"] for k, v in diff.items()},
                coalesce_key=f"connection:{conn.id}:{','.join(sorted(diff.keys()))}",
            )

    return conn


async def flip_connection(
    db: AsyncSession,
    conn: Connection,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> Connection:
    # Capture pre-flip endpoint fields so undo can swap them back via the
    # generic UPDATE apply path. An empty inverse_payload would make undo a
    # no-op since `_apply_update` only writes the keys present in `before`.
    pre_flip = {
        "source_id": str(conn.source_id),
        "target_id": str(conn.target_id),
        "source_handle": conn.source_handle,
        "target_handle": conn.target_handle,
    }
    ws_id_pre_source = conn.source_id  # workspace lookup uses pre-flip source

    conn.source_id, conn.target_id = conn.target_id, conn.source_id
    conn.source_handle, conn.target_handle = conn.target_handle, conn.source_handle
    await db.flush()
    await db.refresh(conn)

    if (
        actor_user is not None
        and from_diagram_id is not None
    ):
        ws_id = await _source_workspace_id(db, ws_id_pre_source)
        if ws_id is not None:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            after_fields = {
                "source_id": str(conn.source_id),
                "target_id": str(conn.target_id),
                "source_handle": conn.source_handle,
                "target_handle": conn.target_handle,
            }
            await undo_service.record(
                db,
                user_id=actor_user.id,
                workspace_id=ws_id,
                diagram_id=from_diagram_id,
                draft_id=from_draft_id,
                target_type=UndoTargetType.CONNECTION,
                target_id=conn.id,
                action=UndoAction.UPDATE,
                forward_summary=f"Flipped connection {str(conn.id)[:8]}"[:80],
                inverse_payload={"before": pre_flip},
                after_state=after_fields,
                coalesce_key=f"connection:{conn.id}:flip",
            )

    return conn


async def delete_connection(
    db: AsyncSession,
    conn: Connection,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
) -> None:
    # Capture snapshot BEFORE delete — include metadata so restore_service
    # can rebuild the connection on undo.
    snapshot = activity_service.snapshot(conn, include_metadata=True)
    conn_id = conn.id

    # Undo recording — need workspace before deleting (derive from source)
    ws_id: uuid.UUID | None = None
    if actor_user is not None and from_diagram_id is not None:
        ws_id = await _source_workspace_id(db, conn.source_id)

    await db.delete(conn)
    await db.flush()

    if (
        actor_user is not None
        and from_diagram_id is not None
        and ws_id is not None
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=ws_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.CONNECTION,
            target_id=conn_id,
            action=UndoAction.DELETE,
            forward_summary=f"Deleted connection {str(conn_id)[:8]}"[:80],
            inverse_payload={"snapshot": snapshot, "id": str(conn_id)},
            after_state=None,
            coalesce_key=f"connection:{conn_id}:delete",
        )


def _summarise_connection_diff(conn: Connection, diff: dict) -> str:
    """Human-readable label for the history popover. Max ~80 chars."""
    fields = ", ".join(sorted(diff.keys()))
    return f"Edited connection — {fields}"[:80]
