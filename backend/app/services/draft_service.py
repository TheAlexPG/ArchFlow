"""Draft = feature branch that can fork N diagrams at once.

The user clicks "Draft new feature" on a live diagram. This service:
  1. Creates a Draft row.
  2. Creates a DraftDiagram row linking the source to a forked clone.

Additional live diagrams can be added later via add_diagram_to_draft.

On ``apply`` we iterate every DraftDiagram, copy each fork back onto its
source (using source_object_id / source_connection_id back-pointers), then
delete all remaining draft-scoped rows and mark the Draft MERGED.

On ``discard`` we delete every fork clone and mark the Draft DISCARDED.
"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.connection import Connection
from app.models.diagram import Diagram, DiagramObject
from app.models.draft import Draft, DraftDiagram, DraftStatus
from app.models.object import ModelObject
from app.schemas.draft import DraftCreate, DraftUpdate

# Editable fields copied during fork + apply. Keep in sync with ObjectCreate
# / ConnectionCreate; skipping internal/bookkeeping columns.
_OBJECT_EDITABLE_FIELDS = (
    "name",
    "type",
    "scope",
    "status",
    "description",
    "icon",
    "technology",
    "tags",
    "owner_team",
    "external_links",
)

_CONNECTION_EDITABLE_FIELDS = (
    "label",
    "protocol",
    "direction",
    "tags",
    "source_handle",
    "target_handle",
    "shape",
    "label_size",
    "via_object_ids",
)


async def list_drafts(db: AsyncSession) -> list[Draft]:
    result = await db.execute(
        select(Draft)
        .options(
            selectinload(Draft.diagrams).selectinload(DraftDiagram.source_diagram),
            selectinload(Draft.diagrams).selectinload(DraftDiagram.forked_diagram),
        )
        .order_by(Draft.created_at.desc())
    )
    return list(result.scalars().all())


async def get_draft(db: AsyncSession, draft_id: uuid.UUID) -> Draft | None:
    result = await db.execute(
        select(Draft)
        .where(Draft.id == draft_id)
        .options(
            selectinload(Draft.diagrams).selectinload(DraftDiagram.source_diagram),
            selectinload(Draft.diagrams).selectinload(DraftDiagram.forked_diagram),
        )
    )
    return result.scalar_one_or_none()


async def create_draft(
    db: AsyncSession, data: DraftCreate, author_id: uuid.UUID | None = None
) -> Draft:
    draft = Draft(
        name=data.name,
        description=data.description,
        author_id=author_id,
    )
    db.add(draft)
    await db.flush()
    # Re-query with eager-loaded relationships (new draft has no DraftDiagrams yet).
    loaded = await get_draft(db, draft.id)
    return loaded  # type: ignore[return-value]


async def update_draft(db: AsyncSession, draft: Draft, data: DraftUpdate) -> Draft:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    await db.flush()
    # Expire so get_draft re-fetches all relationships cleanly.
    db.expire(draft)
    loaded = await get_draft(db, draft.id)
    return loaded  # type: ignore[return-value]


async def delete_draft(db: AsyncSession, draft: Draft) -> None:
    # Cascade removes forked rows (draft_id FK is ON DELETE CASCADE) and the
    # forked diagram (diagrams.draft_id also cascades).
    await db.delete(draft)
    await db.flush()


def _copy_fields(source: Any, dest: Any, fields: tuple[str, ...]) -> None:
    for field in fields:
        setattr(dest, field, getattr(source, field))


async def _clone_diagram(
    db: AsyncSession, draft: Draft, source_diagram: Diagram
) -> Diagram:
    """Clone ``source_diagram`` and everything it references into the draft.

    Returns the new forked Diagram. Does NOT touch any Draft column —
    the caller creates the DraftDiagram row.
    """
    # 1) Clone the diagram row.
    forked_diagram = Diagram(
        name=f"{source_diagram.name} (draft: {draft.name})",
        type=source_diagram.type,
        description=source_diagram.description,
        scope_object_id=source_diagram.scope_object_id,
        settings=source_diagram.settings,
        draft_id=draft.id,
    )
    db.add(forked_diagram)
    await db.flush()

    # 2) Fetch all DiagramObject rows on the source diagram.
    do_rows = (
        await db.execute(
            select(DiagramObject).where(DiagramObject.diagram_id == source_diagram.id)
        )
    ).scalars().all()

    source_object_ids = [do.object_id for do in do_rows]
    if not source_object_ids:
        return forked_diagram

    # 3) Clone the ModelObjects referenced by the source diagram.
    source_objects = (
        await db.execute(select(ModelObject).where(ModelObject.id.in_(source_object_ids)))
    ).scalars().all()

    object_map: dict[uuid.UUID, uuid.UUID] = {}
    for src_obj in source_objects:
        forked_obj = ModelObject(
            name=src_obj.name,
            type=src_obj.type,
            scope=src_obj.scope,
            status=src_obj.status,
            description=src_obj.description,
            icon=src_obj.icon,
            technology=src_obj.technology,
            tags=src_obj.tags,
            owner_team=src_obj.owner_team,
            external_links=src_obj.external_links,
            metadata_=src_obj.metadata_,
            draft_id=draft.id,
            source_object_id=src_obj.id,
        )
        db.add(forked_obj)
        await db.flush()
        object_map[src_obj.id] = forked_obj.id

    # 4) Clone DiagramObject placements, rewiring object_id → forked object.
    for do in do_rows:
        forked_do = DiagramObject(
            diagram_id=forked_diagram.id,
            object_id=object_map[do.object_id],
            position_x=do.position_x,
            position_y=do.position_y,
            width=do.width,
            height=do.height,
        )
        db.add(forked_do)

    # 5) Clone Connections between forked objects.
    conn_rows = (
        await db.execute(
            select(Connection).where(
                Connection.source_id.in_(source_object_ids),
                Connection.target_id.in_(source_object_ids),
                Connection.draft_id.is_(None),
            )
        )
    ).scalars().all()

    for conn in conn_rows:
        forked_conn = Connection(
            source_id=object_map[conn.source_id],
            target_id=object_map[conn.target_id],
            label=conn.label,
            protocol=conn.protocol,
            direction=conn.direction,
            tags=conn.tags,
            source_handle=conn.source_handle,
            target_handle=conn.target_handle,
            shape=conn.shape,
            label_size=conn.label_size,
            via_object_ids=conn.via_object_ids,
            draft_id=draft.id,
            source_connection_id=conn.id,
        )
        db.add(forked_conn)

    await db.flush()
    return forked_diagram


# Keep the old name as an alias so existing call-sites inside the file still work.
fork_diagram_into_draft = _clone_diagram


async def add_diagram_to_draft(
    db: AsyncSession, draft: Draft, source_diagram_id: uuid.UUID
) -> DraftDiagram:
    """Add a live diagram to an existing open draft.

    Raises ValueError when:
    - The draft is not OPEN.
    - The source diagram is itself a fork (draft_id IS NOT NULL).
    - A DraftDiagram for this (draft, source) pair already exists.
    """
    if draft.status != DraftStatus.OPEN:
        raise ValueError(f"Draft is {draft.status.value}, cannot add diagrams")

    source_diagram = await db.get(Diagram, source_diagram_id)
    if source_diagram is None:
        raise ValueError("Source diagram not found")
    if source_diagram.draft_id is not None:
        raise ValueError("Cannot add a fork to a draft")

    # Check for duplicate.
    existing = (
        await db.execute(
            select(DraftDiagram).where(
                DraftDiagram.draft_id == draft.id,
                DraftDiagram.source_diagram_id == source_diagram_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("Diagram already in this draft")

    forked = await _clone_diagram(db, draft, source_diagram)

    dd = DraftDiagram(
        draft_id=draft.id,
        source_diagram_id=source_diagram_id,
        forked_diagram_id=forked.id,
    )
    db.add(dd)
    await db.flush()
    await db.refresh(dd)
    return dd


async def remove_diagram_from_draft(
    db: AsyncSession, draft: Draft, source_diagram_id: uuid.UUID
) -> None:
    """Remove a diagram from the draft; deletes the fork clone."""
    dd = (
        await db.execute(
            select(DraftDiagram).where(
                DraftDiagram.draft_id == draft.id,
                DraftDiagram.source_diagram_id == source_diagram_id,
            )
        )
    ).scalar_one_or_none()
    if dd is None:
        raise ValueError("Diagram not found in this draft")

    # Delete all draft-scoped connections and objects for this fork.
    forked_diagram = await db.get(Diagram, dd.forked_diagram_id)

    # Get forked object ids to clean up connections scoped to this draft
    # (connections carry draft_id but may span multiple forked diagrams in
    # edge cases; we scope deletion to objects of THIS fork).
    forked_placements = (
        await db.execute(
            select(DiagramObject).where(
                DiagramObject.diagram_id == dd.forked_diagram_id
            )
        )
    ).scalars().all()
    forked_obj_ids = [p.object_id for p in forked_placements]

    if forked_obj_ids:
        await db.execute(
            delete(Connection).where(
                Connection.draft_id == draft.id,
                Connection.source_id.in_(forked_obj_ids),
            )
        )
        await db.execute(
            delete(ModelObject).where(
                ModelObject.draft_id == draft.id,
                ModelObject.id.in_(forked_obj_ids),
            )
        )

    if forked_diagram is not None:
        await db.delete(forked_diagram)

    await db.delete(dd)
    await db.flush()


async def _apply_single_diagram(
    db: AsyncSession,
    draft: Draft,
    dd: DraftDiagram,
) -> dict:
    """Apply a single DraftDiagram fork onto its source. Returns count summary."""
    updated_objects = 0
    created_objects = 0
    updated_connections = 0
    created_connections = 0
    deleted_objects = 0
    deleted_connections = 0

    # ── Objects ───────────────────────────────────────────────────
    # Only objects that belong to THIS fork (placed on the forked diagram).
    fork_placements = (
        await db.execute(
            select(DiagramObject).where(
                DiagramObject.diagram_id == dd.forked_diagram_id
            )
        )
    ).scalars().all()
    fork_object_ids = {p.object_id for p in fork_placements}

    forked_objects = list(
        (
            await db.execute(
                select(ModelObject).where(
                    ModelObject.draft_id == draft.id,
                    ModelObject.id.in_(fork_object_ids),
                )
            )
        ).scalars().all()
    )

    promoted_object_ids: dict[uuid.UUID, uuid.UUID] = {}

    live_objects_by_source: dict[uuid.UUID, ModelObject] = {}
    for fo in forked_objects:
        if fo.source_object_id:
            live = await db.get(ModelObject, fo.source_object_id)
            if live is not None:
                live_objects_by_source[fo.source_object_id] = live

    # Find source objects that were on the live diagram but are no longer
    # represented in the fork (user deleted them). Delete those on live too.
    source_diagram_object_ids = {
        row.object_id
        for row in (
            await db.execute(
                select(DiagramObject).where(
                    DiagramObject.diagram_id == dd.source_diagram_id
                )
            )
        ).scalars().all()
    }
    forked_source_object_ids = {
        fo.source_object_id for fo in forked_objects if fo.source_object_id
    }
    removed_live_object_ids = source_diagram_object_ids - forked_source_object_ids
    for obj_id in removed_live_object_ids:
        live = await db.get(ModelObject, obj_id)
        if live is not None:
            await db.delete(live)
            deleted_objects += 1
    await db.flush()

    for fo in forked_objects:
        if fo.source_object_id:
            live = live_objects_by_source.get(fo.source_object_id)
            if live is None:
                fo.draft_id = None
                fo.source_object_id = None
                promoted_object_ids[fo.id] = fo.id
                created_objects += 1
                continue
            _copy_fields(fo, live, _OBJECT_EDITABLE_FIELDS)
            promoted_object_ids[fo.id] = live.id
            updated_objects += 1
        else:
            fo.draft_id = None
            promoted_object_ids[fo.id] = fo.id
            created_objects += 1
    await db.flush()

    # ── Connections ────────────────────────────────────────────────
    forked_connections = list(
        (
            await db.execute(
                select(Connection).where(
                    Connection.draft_id == draft.id,
                    Connection.source_id.in_(fork_object_ids),
                    Connection.target_id.in_(fork_object_ids),
                )
            )
        ).scalars().all()
    )

    source_object_ids_set = source_diagram_object_ids
    source_connections = list(
        (
            await db.execute(
                select(Connection).where(
                    Connection.source_id.in_(source_object_ids_set or [uuid.uuid4()]),
                    Connection.target_id.in_(source_object_ids_set or [uuid.uuid4()]),
                    Connection.draft_id.is_(None),
                )
            )
        ).scalars().all()
    )
    forked_source_connection_ids = {
        fc.source_connection_id for fc in forked_connections if fc.source_connection_id
    }
    for conn in source_connections:
        if conn.id not in forked_source_connection_ids:
            await db.delete(conn)
            deleted_connections += 1
    await db.flush()

    for fc in forked_connections:
        remapped_source = promoted_object_ids.get(fc.source_id, fc.source_id)
        remapped_target = promoted_object_ids.get(fc.target_id, fc.target_id)

        if fc.source_connection_id:
            live_conn = await db.get(Connection, fc.source_connection_id)
            if live_conn is None:
                fc.source_id = remapped_source
                fc.target_id = remapped_target
                fc.draft_id = None
                fc.source_connection_id = None
                created_connections += 1
                continue
            _copy_fields(fc, live_conn, _CONNECTION_EDITABLE_FIELDS)
            live_conn.source_id = remapped_source
            live_conn.target_id = remapped_target
            updated_connections += 1
        else:
            fc.source_id = remapped_source
            fc.target_id = remapped_target
            fc.draft_id = None
            fc.source_connection_id = None
            created_connections += 1
    await db.flush()

    # ── Placements ─────────────────────────────────────────────────
    forked_placements_list = list(fork_placements)
    await db.execute(
        delete(DiagramObject).where(
            DiagramObject.diagram_id == dd.source_diagram_id
        )
    )
    for fp in forked_placements_list:
        live_obj_id = promoted_object_ids.get(fp.object_id, fp.object_id)
        db.add(
            DiagramObject(
                diagram_id=dd.source_diagram_id,
                object_id=live_obj_id,
                position_x=fp.position_x,
                position_y=fp.position_y,
                width=fp.width,
                height=fp.height,
            )
        )
    await db.flush()

    return {
        "updated_objects": updated_objects,
        "created_objects": created_objects,
        "deleted_objects": deleted_objects,
        "updated_connections": updated_connections,
        "created_connections": created_connections,
        "deleted_connections": deleted_connections,
    }


async def apply_draft(db: AsyncSession, draft: Draft) -> dict:
    """Merge all forks back onto their respective live source diagrams."""
    if draft.status != DraftStatus.OPEN:
        raise ValueError(f"Draft is {draft.status.value}, cannot apply")

    # Reload diagrams relationship to ensure it's populated.
    draft_diagrams = list(
        (
            await db.execute(
                select(DraftDiagram).where(DraftDiagram.draft_id == draft.id)
            )
        ).scalars().all()
    )

    if not draft_diagrams:
        raise ValueError("Draft is empty")

    totals: dict[str, int] = {
        "updated_objects": 0,
        "created_objects": 0,
        "deleted_objects": 0,
        "updated_connections": 0,
        "created_connections": 0,
        "deleted_connections": 0,
        "applied_diagrams": 0,
    }

    for dd in draft_diagrams:
        counts = await _apply_single_diagram(db, draft, dd)
        for k, v in counts.items():
            totals[k] += v
        totals["applied_diagrams"] += 1

    # Cleanup: delete any remaining draft-scoped rows (orphans after promote).
    await db.execute(delete(Connection).where(Connection.draft_id == draft.id))
    await db.execute(delete(ModelObject).where(ModelObject.draft_id == draft.id))

    # Delete forked diagrams (and DraftDiagram rows via cascade).
    for dd in draft_diagrams:
        forked = await db.get(Diagram, dd.forked_diagram_id)
        if forked is not None:
            await db.delete(forked)

    draft.status = DraftStatus.MERGED
    await db.flush()
    await db.refresh(draft, ["diagrams"])

    return {
        "draft_id": str(draft.id),
        "status": draft.status.value,
        **totals,
    }


def _object_fields_equal(a: ModelObject, b: ModelObject) -> bool:
    """True iff the two objects have identical editable fields."""
    return all(getattr(a, field) == getattr(b, field) for field in _OBJECT_EDITABLE_FIELDS)


def _connection_fields_equal(a: Connection, b: Connection) -> bool:
    return all(getattr(a, field) == getattr(b, field) for field in _CONNECTION_EDITABLE_FIELDS)


async def _compute_single_diagram_diff(
    db: AsyncSession, draft: Draft, dd: DraftDiagram
) -> dict:
    """Compute diff for one DraftDiagram. Returns per-diagram diff dict."""
    source_placements = (
        await db.execute(
            select(DiagramObject).where(
                DiagramObject.diagram_id == dd.source_diagram_id
            )
        )
    ).scalars().all()
    fork_placements = (
        await db.execute(
            select(DiagramObject).where(
                DiagramObject.diagram_id == dd.forked_diagram_id
            )
        )
    ).scalars().all()

    source_object_ids = {p.object_id for p in source_placements}
    fork_object_ids = {p.object_id for p in fork_placements}

    live_objects_by_id: dict[uuid.UUID, ModelObject] = {}
    if source_object_ids:
        rows = (
            await db.execute(
                select(ModelObject).where(ModelObject.id.in_(source_object_ids))
            )
        ).scalars().all()
        live_objects_by_id = {o.id: o for o in rows}

    forked_objects_by_id: dict[uuid.UUID, ModelObject] = {}
    if fork_object_ids:
        rows = (
            await db.execute(
                select(ModelObject).where(ModelObject.id.in_(fork_object_ids))
            )
        ).scalars().all()
        forked_objects_by_id = {o.id: o for o in rows}

    fork_source_ids: set[uuid.UUID] = set()
    source_objects: dict[str, str] = {}
    fork_objects: dict[str, str] = {}
    moved_on_fork: list[str] = []
    resized_on_fork: list[str] = []
    added = 0
    modified_objs = 0

    src_pos: dict[uuid.UUID, DiagramObject] = {p.object_id: p for p in source_placements}
    fork_pos: dict[uuid.UUID, DiagramObject] = {p.object_id: p for p in fork_placements}

    for fid, fobj in forked_objects_by_id.items():
        if fobj.source_object_id is None:
            fork_objects[str(fid)] = "new"
            added += 1
            continue
        live = live_objects_by_id.get(fobj.source_object_id)
        fork_source_ids.add(fobj.source_object_id)
        if live is None:
            fork_objects[str(fid)] = "new"
            added += 1
            continue
        if _object_fields_equal(live, fobj):
            fork_objects[str(fid)] = "unchanged"
        else:
            fork_objects[str(fid)] = "modified"
            modified_objs += 1
        sp = src_pos.get(fobj.source_object_id)
        fp = fork_pos.get(fid)
        if sp and fp:
            if (sp.position_x, sp.position_y) != (fp.position_x, fp.position_y):
                moved_on_fork.append(str(fid))
            if (sp.width, sp.height) != (fp.width, fp.height):
                resized_on_fork.append(str(fid))

    deleted = 0
    for lid in live_objects_by_id:
        if lid in fork_source_ids:
            matched_status = "unchanged"
            for fid, fobj in forked_objects_by_id.items():
                if fobj.source_object_id == lid:
                    matched_status = fork_objects[str(fid)]
                    break
            source_objects[str(lid)] = (
                "modified" if matched_status == "modified" else "unchanged"
            )
        else:
            source_objects[str(lid)] = "deleted"
            deleted += 1

    # ── Connections ────────────────────────────────────────────
    source_conns = (
        await db.execute(
            select(Connection).where(
                Connection.source_id.in_(source_object_ids or [uuid.uuid4()]),
                Connection.target_id.in_(source_object_ids or [uuid.uuid4()]),
                Connection.draft_id.is_(None),
            )
        )
    ).scalars().all()
    fork_conns_all = (
        await db.execute(
            select(Connection).where(Connection.draft_id == draft.id)
        )
    ).scalars().all()
    fork_conns = [
        c for c in fork_conns_all
        if c.source_id in fork_object_ids and c.target_id in fork_object_ids
    ]

    source_connections: dict[str, str] = {}
    fork_connections: dict[str, str] = {}
    added_conn = 0
    modified_conn = 0

    live_conns_by_id = {c.id: c for c in source_conns}
    matched_source_conn_ids: set[uuid.UUID] = set()

    for fc in fork_conns:
        if fc.source_connection_id is None:
            fork_connections[str(fc.id)] = "new"
            added_conn += 1
            continue
        live = live_conns_by_id.get(fc.source_connection_id)
        if live is None:
            fork_connections[str(fc.id)] = "new"
            added_conn += 1
            continue
        matched_source_conn_ids.add(live.id)
        if _connection_fields_equal(live, fc):
            fork_connections[str(fc.id)] = "unchanged"
        else:
            fork_connections[str(fc.id)] = "modified"
            modified_conn += 1

    deleted_conn = 0
    for sc in source_conns:
        if sc.id in matched_source_conn_ids:
            matched_status = "unchanged"
            for fc in fork_conns:
                if fc.source_connection_id == sc.id:
                    matched_status = fork_connections[str(fc.id)]
                    break
            source_connections[str(sc.id)] = (
                "modified" if matched_status == "modified" else "unchanged"
            )
        else:
            source_connections[str(sc.id)] = "deleted"
            deleted_conn += 1

    object_names: dict[str, str] = {}
    for lid, lo in live_objects_by_id.items():
        object_names[str(lid)] = lo.name
    for fid, fo in forked_objects_by_id.items():
        object_names[str(fid)] = fo.name

    # Fetch names for source/forked diagrams.
    source_diag = await db.get(Diagram, dd.source_diagram_id)
    forked_diag = await db.get(Diagram, dd.forked_diagram_id)

    return {
        "source_diagram_id": str(dd.source_diagram_id),
        "forked_diagram_id": str(dd.forked_diagram_id),
        "source_diagram_name": source_diag.name if source_diag else None,
        "forked_diagram_name": forked_diag.name if forked_diag else None,
        "source_objects": source_objects,
        "fork_objects": fork_objects,
        "source_connections": source_connections,
        "fork_connections": fork_connections,
        "moved_on_fork": moved_on_fork,
        "resized_on_fork": resized_on_fork,
        "object_names": object_names,
        "summary": {
            "added_objects": added,
            "modified_objects": modified_objs,
            "deleted_objects": deleted,
            "added_connections": added_conn,
            "modified_connections": modified_conn,
            "deleted_connections": deleted_conn,
            "moved_objects": len(moved_on_fork),
            "resized_objects": len(resized_on_fork),
        },
    }


async def compute_diff(db: AsyncSession, draft: Draft) -> dict:
    """Compute a per-diagram diff for the compare UI."""
    draft_diagrams = list(
        (
            await db.execute(
                select(DraftDiagram).where(DraftDiagram.draft_id == draft.id)
            )
        ).scalars().all()
    )

    if not draft_diagrams:
        zeros = {
            "added_objects": 0,
            "modified_objects": 0,
            "deleted_objects": 0,
            "added_connections": 0,
            "modified_connections": 0,
            "deleted_connections": 0,
            "moved_objects": 0,
            "resized_objects": 0,
        }
        return {"diagrams": [], "total_summary": zeros}

    diagrams_diff = []
    totals: dict[str, int] = {
        "added_objects": 0,
        "modified_objects": 0,
        "deleted_objects": 0,
        "added_connections": 0,
        "modified_connections": 0,
        "deleted_connections": 0,
        "moved_objects": 0,
        "resized_objects": 0,
    }

    for dd in draft_diagrams:
        per_diag = await _compute_single_diagram_diff(db, draft, dd)
        diagrams_diff.append(per_diag)
        for k in totals:
            totals[k] += per_diag["summary"].get(k, 0)

    return {"diagrams": diagrams_diff, "total_summary": totals}


async def discard_draft(db: AsyncSession, draft: Draft) -> Draft:
    """Delete all fork clones and mark draft DISCARDED."""
    draft_diagrams = list(
        (
            await db.execute(
                select(DraftDiagram).where(DraftDiagram.draft_id == draft.id)
            )
        ).scalars().all()
    )

    # Delete all draft-scoped connections and objects.
    await db.execute(delete(Connection).where(Connection.draft_id == draft.id))
    await db.execute(delete(ModelObject).where(ModelObject.draft_id == draft.id))

    for dd in draft_diagrams:
        forked = await db.get(Diagram, dd.forked_diagram_id)
        if forked is not None:
            await db.delete(forked)

    draft.status = DraftStatus.DISCARDED
    await db.flush()
    await db.refresh(draft)
    return draft


async def fork_existing_diagram(
    db: AsyncSession,
    source_diagram_id: uuid.UUID,
    draft_data: DraftCreate,
    author_id: uuid.UUID | None = None,
) -> tuple[Draft, DraftDiagram]:
    """One-shot helper: create a Draft and fork one diagram into it.

    Returns (Draft, DraftDiagram).
    """
    source = await db.execute(
        select(Diagram)
        .where(Diagram.id == source_diagram_id, Diagram.draft_id.is_(None))
        .options(selectinload(Diagram.objects))
    )
    source_diagram = source.scalar_one_or_none()
    if source_diagram is None:
        raise ValueError("Source diagram not found (or is itself a forked draft)")

    draft = await create_draft(db, draft_data, author_id=author_id)
    forked = await _clone_diagram(db, draft, source_diagram)

    dd = DraftDiagram(
        draft_id=draft.id,
        source_diagram_id=source_diagram_id,
        forked_diagram_id=forked.id,
    )
    db.add(dd)
    await db.flush()

    # Expire the in-memory Draft so selectinload in get_draft re-fetches the
    # now-populated diagrams collection (the identity map would otherwise
    # return the stale empty list).
    await db.refresh(draft)
    db.expire(draft, ["diagrams"])

    # Re-query so that DraftDiagram sub-relationships (source_diagram,
    # forked_diagram) are eagerly loaded before returning.
    loaded_draft = await get_draft(db, draft.id)
    return loaded_draft, dd


async def get_drafts_for_diagram(
    db: AsyncSession, source_diagram_id: uuid.UUID
) -> list[dict]:
    """Return all OPEN drafts that include the given source diagram."""
    rows = (
        await db.execute(
            select(DraftDiagram, Draft)
            .join(Draft, Draft.id == DraftDiagram.draft_id)
            .where(
                DraftDiagram.source_diagram_id == source_diagram_id,
                Draft.status == DraftStatus.OPEN,
            )
        )
    ).all()

    result = []
    for dd, draft in rows:
        result.append(
            {
                "draft_id": str(draft.id),
                "draft_name": draft.name,
                "draft_status": draft.status.value,
                "source_diagram_id": str(dd.source_diagram_id),
                "forked_diagram_id": str(dd.forked_diagram_id),
            }
        )
    return result
