"""Versioning service — immutable snapshots of the full workspace model.

A snapshot is a JSONB blob with every model_object, connection, and diagram
(plus their per-diagram placements) that lives in the workspace at a moment
in time. The shape is intentionally flat + primitive so diffs can run in
Python without hitting the live tables.
"""
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.diagram import Diagram, DiagramObject
from app.models.object import ModelObject
from app.models.version import Version, VersionSource


OBJECT_FIELDS = (
    "id",
    "name",
    "type",
    "scope",
    "status",
    "description",
    "icon",
    "parent_id",
    "technology_ids",
    "tags",
    "owner_team",
    "external_links",
    "metadata_",
    "workspace_id",
)

CONNECTION_FIELDS = (
    "id",
    "source_id",
    "target_id",
    "label",
    "direction",
    "protocol_ids",
    "tags",
)

DIAGRAM_FIELDS = (
    "id",
    "name",
    "type",
    "description",
    "scope_object_id",
    "settings",
    "pinned",
    "workspace_id",
)

PLACEMENT_FIELDS = (
    "object_id",
    "position_x",
    "position_y",
    "width",
    "height",
)


def _serialize_row(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields:
        value = getattr(row, f, None)
        if isinstance(value, uuid.UUID):
            out[f] = str(value)
        elif hasattr(value, "value"):
            # Enum → use the DB value so round-tripping diffs compare strings.
            out[f] = value.value
        else:
            out[f] = value
    return out


async def _snapshot_workspace(
    db: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, Any]:
    """Dump every live (non-draft) object/connection/diagram in the
    workspace into a plain dict tree."""
    objects = (
        await db.execute(
            select(ModelObject).where(
                ModelObject.workspace_id == workspace_id,
                ModelObject.draft_id.is_(None),
            )
        )
    ).scalars().all()

    diagrams = (
        await db.execute(
            select(Diagram).where(
                Diagram.workspace_id == workspace_id,
                Diagram.draft_id.is_(None),
            )
        )
    ).scalars().all()

    diagram_ids = [d.id for d in diagrams]
    placements_by_diagram: dict[str, list[dict]] = {}
    if diagram_ids:
        rows = (
            await db.execute(
                select(DiagramObject).where(
                    DiagramObject.diagram_id.in_(diagram_ids)
                )
            )
        ).scalars().all()
        for p in rows:
            placements_by_diagram.setdefault(str(p.diagram_id), []).append(
                _serialize_row(p, PLACEMENT_FIELDS)
            )

    object_ids = {o.id for o in objects}
    connections: list[Connection] = []
    if object_ids:
        connections = list(
            (
                await db.execute(
                    select(Connection).where(
                        Connection.source_id.in_(object_ids),
                        Connection.target_id.in_(object_ids),
                        Connection.draft_id.is_(None),
                    )
                )
            ).scalars().all()
        )

    return {
        "objects": [_serialize_row(o, OBJECT_FIELDS) for o in objects],
        "connections": [_serialize_row(c, CONNECTION_FIELDS) for c in connections],
        "diagrams": [
            {
                **_serialize_row(d, DIAGRAM_FIELDS),
                "placements": placements_by_diagram.get(str(d.id), []),
            }
            for d in diagrams
        ],
    }


async def _next_label(db: AsyncSession, workspace_id: uuid.UUID) -> str:
    """Label format v1.0, v1.1, v1.2… — monotonic by (workspace, created_at).

    Cheap and readable. Doesn't try to be semantic (no major/minor by
    intent); picking real semver would need user input.
    """
    count = (
        await db.execute(
            select(func.count(Version.id)).where(
                Version.workspace_id == workspace_id
            )
        )
    ).scalar_one()
    return f"v1.{count}"


async def create_snapshot(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    source: VersionSource,
    draft_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
) -> Version:
    snapshot_data = await _snapshot_workspace(db, workspace_id)
    label = await _next_label(db, workspace_id)
    version = Version(
        workspace_id=workspace_id,
        label=label,
        source=source,
        draft_id=draft_id,
        snapshot_data=snapshot_data,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return version


async def list_versions(
    db: AsyncSession, workspace_id: uuid.UUID, limit: int = 200
) -> list[Version]:
    result = await db.execute(
        select(Version)
        .where(Version.workspace_id == workspace_id)
        .order_by(Version.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_version(
    db: AsyncSession, workspace_id: uuid.UUID, version_id: uuid.UUID
) -> Version | None:
    result = await db.execute(
        select(Version).where(
            Version.id == version_id, Version.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


# ──────────────────────────────────────────────────────────────────────
# Diff helpers — used by both the compare endpoint and conflict detection.


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """id → row lookup for O(1) diff access."""
    return {r["id"]: r for r in rows}


def diff_snapshots(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Flat, entity-wise diff.

    Returns per-kind sets of ids: added / removed / modified. Doesn't dig
    into which field changed — callers that need field-level detail can
    ask for the full snapshot. Good enough for conflict detection where we
    just need "did both sides touch this id".
    """
    out = {}
    for kind, fields in (
        ("objects", OBJECT_FIELDS),
        ("connections", CONNECTION_FIELDS),
        ("diagrams", DIAGRAM_FIELDS),
    ):
        before_idx = _index(before.get(kind, []))
        after_idx = _index(after.get(kind, []))
        added = sorted(set(after_idx) - set(before_idx))
        removed = sorted(set(before_idx) - set(after_idx))
        modified = sorted(
            k
            for k in set(before_idx) & set(after_idx)
            if any(before_idx[k].get(f) != after_idx[k].get(f) for f in fields)
        )
        out[kind] = {
            "added": added,
            "removed": removed,
            "modified": modified,
        }
    return out


def summarize_diff(diff: dict[str, Any]) -> dict[str, int]:
    flat: dict[str, int] = {}
    for kind in ("objects", "connections", "diagrams"):
        part = diff.get(kind, {})
        flat[f"{kind}_added"] = len(part.get("added", []))
        flat[f"{kind}_removed"] = len(part.get("removed", []))
        flat[f"{kind}_modified"] = len(part.get("modified", []))
    return flat


# ──────────────────────────────────────────────────────────────────────
# Revert — apply a snapshot back onto live tables.


async def _revert_entity(
    db: AsyncSession,
    model_cls: type,
    snapshot_rows: list[dict[str, Any]],
    workspace_id: uuid.UUID,
    fields: tuple[str, ...],
    live_query_override: Any = None,
) -> None:
    """Upsert every row from the snapshot, delete live rows that aren't in
    it. Scoped to workspace + draft_id IS NULL so we never touch rows from
    other workspaces or still-open drafts.

    `live_query_override` lets callers supply a pre-built query for models
    that don't have workspace_id directly (connections live under their
    endpoint objects).
    """
    snapshot_by_id = {
        uuid.UUID(r["id"]): r for r in snapshot_rows
    }

    from sqlalchemy import delete

    if live_query_override is not None:
        live_query = live_query_override
    else:
        live_query = select(model_cls).where(model_cls.workspace_id == workspace_id)
    if hasattr(model_cls, "draft_id"):
        live_query = live_query.where(model_cls.draft_id.is_(None))
    live_rows = list((await db.execute(live_query)).scalars().all())

    live_ids = {r.id for r in live_rows}
    snapshot_ids = set(snapshot_by_id.keys())

    # Delete rows no longer in the snapshot.
    to_delete = live_ids - snapshot_ids
    if to_delete:
        del_q = delete(model_cls).where(model_cls.id.in_(to_delete))
        await db.execute(del_q)

    live_by_id = {r.id: r for r in live_rows if r.id in snapshot_ids}

    for sid, sdata in snapshot_by_id.items():
        if sid in live_by_id:
            row = live_by_id[sid]
            for f in fields:
                if f == "id":
                    continue
                if f not in sdata:
                    continue
                value = sdata[f]
                # Convert string UUID references back to UUID objects.
                if f.endswith("_id") and isinstance(value, str):
                    try:
                        value = uuid.UUID(value)
                    except ValueError:
                        pass
                setattr(row, f, value)
        else:
            # Row was deleted after the snapshot — re-insert it.
            kwargs: dict[str, Any] = {}
            for f in fields:
                if f not in sdata:
                    continue
                value = sdata[f]
                if f.endswith("_id") and isinstance(value, str):
                    try:
                        value = uuid.UUID(value)
                    except ValueError:
                        pass
                # ModelObject maps metadata_ column to "metadata"; snapshot
                # already uses the Python attribute name, so this passes
                # through untouched.
                kwargs[f] = value
            db.add(model_cls(**kwargs))


async def revert_to_snapshot(
    db: AsyncSession,
    version: Version,
    created_by_user_id: uuid.UUID | None = None,
) -> Version:
    """Restore the workspace to the state captured in `version`, then
    persist a new snapshot (source=revert) so the rollback itself is
    auditable.

    Non-destructive: all pre-existing Version rows remain. If the caller
    changes their mind they can revert forward to the post-collision
    version just as easily.
    """
    snapshot = version.snapshot_data
    ws_id = version.workspace_id

    # Objects first, then connections + diagrams (connections FK objects).
    await _revert_entity(
        db, ModelObject, snapshot.get("objects", []), ws_id, OBJECT_FIELDS
    )
    await db.flush()

    # Connections don't have workspace_id — scope via their source object.
    ws_object_ids_q = select(ModelObject.id).where(
        ModelObject.workspace_id == ws_id, ModelObject.draft_id.is_(None)
    )
    conn_live_query = select(Connection).where(
        Connection.source_id.in_(ws_object_ids_q)
    )
    await _revert_entity(
        db,
        Connection,
        snapshot.get("connections", []),
        ws_id,
        CONNECTION_FIELDS,
        live_query_override=conn_live_query,
    )
    await db.flush()

    # Diagrams need special handling — we must also reconcile placements.
    diagram_snapshots = snapshot.get("diagrams", [])
    diagram_rows = [
        {k: v for k, v in d.items() if k != "placements"} for d in diagram_snapshots
    ]
    await _revert_entity(
        db, Diagram, diagram_rows, ws_id, DIAGRAM_FIELDS
    )
    await db.flush()

    # Replay placements: wipe everything for diagrams we just restored,
    # then re-insert from the snapshot.
    from sqlalchemy import delete

    snap_diagram_ids = [uuid.UUID(d["id"]) for d in diagram_snapshots]
    if snap_diagram_ids:
        await db.execute(
            delete(DiagramObject).where(
                DiagramObject.diagram_id.in_(snap_diagram_ids)
            )
        )
        for d in diagram_snapshots:
            diagram_uuid = uuid.UUID(d["id"])
            for p in d.get("placements", []):
                db.add(
                    DiagramObject(
                        diagram_id=diagram_uuid,
                        object_id=uuid.UUID(p["object_id"]),
                        position_x=p.get("position_x") or 0.0,
                        position_y=p.get("position_y") or 0.0,
                        width=p.get("width"),
                        height=p.get("height"),
                    )
                )
    await db.flush()

    return await create_snapshot(
        db,
        workspace_id=ws_id,
        source=VersionSource.REVERT,
        created_by_user_id=created_by_user_id,
    )
