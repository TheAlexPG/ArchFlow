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
    "technology",
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
    "description",
    "direction",
    "technology",
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
