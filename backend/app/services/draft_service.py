"""Draft = forked branch of a diagram.

The user clicks "Draft new feature" on a live diagram, this service clones
the whole diagram (its Diagram row, the ModelObjects that appear on it,
the Connections between those objects, and the DiagramObject placements)
into a parallel set of rows tagged with ``draft_id``. The user edits that
forked diagram on the normal canvas; live reads skip draft-owned rows.

On ``apply`` we walk the fork and, using the ``source_object_id`` /
``source_connection_id`` back-pointers we set during the fork, copy each
forked row's editable fields onto its live source; brand-new forked rows
(no source) get promoted by clearing their draft_id. Then we remove the
forked diagram itself and mark the Draft merged.

On ``discard`` we just delete the fork and mark the Draft discarded.
"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.connection import Connection
from app.models.diagram import Diagram, DiagramObject
from app.models.draft import Draft, DraftStatus
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
        select(Draft).order_by(Draft.created_at.desc())
    )
    return list(result.scalars().all())


async def get_draft(db: AsyncSession, draft_id: uuid.UUID) -> Draft | None:
    result = await db.execute(select(Draft).where(Draft.id == draft_id))
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
    await db.refresh(draft)
    return draft


async def update_draft(db: AsyncSession, draft: Draft, data: DraftUpdate) -> Draft:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(draft, field, value)
    await db.flush()
    await db.refresh(draft)
    return draft


async def delete_draft(db: AsyncSession, draft: Draft) -> None:
    # Cascade removes forked rows (draft_id FK is ON DELETE CASCADE) and the
    # forked diagram (diagrams.draft_id also cascades).
    await db.delete(draft)
    await db.flush()


def _copy_fields(source: Any, dest: Any, fields: tuple[str, ...]) -> None:
    for field in fields:
        setattr(dest, field, getattr(source, field))


async def fork_diagram_into_draft(
    db: AsyncSession, draft: Draft, source_diagram: Diagram
) -> Diagram:
    """Clone ``source_diagram`` and everything it references into the draft.

    Returns the new forked Diagram. Both ``draft.source_diagram_id`` and
    ``draft.forked_diagram_id`` are set. The caller's transaction commits
    everything together.
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

    draft.source_diagram_id = source_diagram.id
    draft.forked_diagram_id = forked_diagram.id

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


async def apply_draft(db: AsyncSession, draft: Draft) -> dict:
    """Merge fork back onto the live source diagram.

    Field updates for forked rows that have a source are copied onto the
    source row. Forked rows without a source (newly added in the draft)
    get their draft_id cleared and become live. Forked-only rows that the
    user removed from the fork simply stay deleted — there's nothing to
    propagate. Missing live objects that the user deleted from the fork
    are deleted on the source.
    """
    if draft.status != DraftStatus.OPEN:
        raise ValueError(f"Draft is {draft.status.value}, cannot apply")
    if not draft.forked_diagram_id or not draft.source_diagram_id:
        raise ValueError("Draft has no forked diagram to apply")

    updated_objects = 0
    created_objects = 0
    updated_connections = 0
    created_connections = 0
    deleted_objects = 0
    deleted_connections = 0

    # ── Objects ───────────────────────────────────────────────────
    forked_objects = list(
        (
            await db.execute(
                select(ModelObject).where(ModelObject.draft_id == draft.id)
            )
        ).scalars().all()
    )

    promoted_object_ids: dict[uuid.UUID, uuid.UUID] = {}
    # maps forked_obj.id -> the live id it represents (either its source,
    # or its own id after promotion). Used to rewire connection FKs.

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
                    DiagramObject.diagram_id == draft.source_diagram_id
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
                # The live source vanished mid-draft; promote the fork instead.
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
                select(Connection).where(Connection.draft_id == draft.id)
            )
        ).scalars().all()
    )

    # Deletes on connections mirror the object rule: source connections not
    # represented in the fork are gone.
    source_object_ids_set = source_diagram_object_ids
    source_connections = list(
        (
            await db.execute(
                select(Connection).where(
                    Connection.source_id.in_(source_object_ids_set),
                    Connection.target_id.in_(source_object_ids_set),
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

    # Forked objects' new live ids are in promoted_object_ids; forked
    # connections may reference forked objects, so we need to remap their
    # source_id/target_id.
    for fc in forked_connections:
        remapped_source = promoted_object_ids.get(fc.source_id, fc.source_id)
        remapped_target = promoted_object_ids.get(fc.target_id, fc.target_id)

        if fc.source_connection_id:
            live_conn = await db.get(Connection, fc.source_connection_id)
            if live_conn is None:
                # Promote the forked connection instead.
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

    # Promoted forked objects need to stay on the SOURCE diagram from now
    # on, and any forked-only objects need DiagramObject entries on the
    # source. Rewire placements: take the fork's DiagramObjects, rewrite
    # object_id via promoted_object_ids, and upsert onto the source diagram.
    forked_placements = list(
        (
            await db.execute(
                select(DiagramObject).where(
                    DiagramObject.diagram_id == draft.forked_diagram_id
                )
            )
        ).scalars().all()
    )
    # Remove the source diagram's existing placements first so we can
    # rewrite the full layout from the fork (the user might have moved
    # things around).
    await db.execute(
        delete(DiagramObject).where(DiagramObject.diagram_id == draft.source_diagram_id)
    )
    for fp in forked_placements:
        live_obj_id = promoted_object_ids.get(fp.object_id, fp.object_id)
        db.add(
            DiagramObject(
                diagram_id=draft.source_diagram_id,
                object_id=live_obj_id,
                position_x=fp.position_x,
                position_y=fp.position_y,
                width=fp.width,
                height=fp.height,
            )
        )

    # ── Cleanup the fork ────────────────────────────────────────
    # Promoted forked rows are now live and must not be wiped. Anything
    # still scoped to this draft is safe to delete.
    await db.execute(
        delete(Connection).where(Connection.draft_id == draft.id)
    )
    await db.execute(
        delete(ModelObject).where(ModelObject.draft_id == draft.id)
    )
    forked_diagram = await db.get(Diagram, draft.forked_diagram_id)
    if forked_diagram is not None:
        await db.delete(forked_diagram)

    draft.status = DraftStatus.MERGED
    draft.forked_diagram_id = None
    await db.flush()

    return {
        "draft_id": str(draft.id),
        "status": draft.status.value,
        "updated_objects": updated_objects,
        "created_objects": created_objects,
        "deleted_objects": deleted_objects,
        "updated_connections": updated_connections,
        "created_connections": created_connections,
        "deleted_connections": deleted_connections,
    }


async def discard_draft(db: AsyncSession, draft: Draft) -> Draft:
    # CASCADE on draft_id FKs removes the fork clone entirely when we
    # null out the marker; but we prefer to explicitly delete so stats
    # are clear and we keep the Draft row for audit.
    await db.execute(
        delete(Connection).where(Connection.draft_id == draft.id)
    )
    await db.execute(
        delete(ModelObject).where(ModelObject.draft_id == draft.id)
    )
    if draft.forked_diagram_id is not None:
        forked = await db.get(Diagram, draft.forked_diagram_id)
        if forked is not None:
            await db.delete(forked)
    draft.status = DraftStatus.DISCARDED
    draft.forked_diagram_id = None
    await db.flush()
    return draft


async def fork_existing_diagram(
    db: AsyncSession,
    source_diagram_id: uuid.UUID,
    draft_data: DraftCreate,
    author_id: uuid.UUID | None = None,
) -> tuple[Draft, Diagram]:
    """One-shot helper used by the API endpoint that starts a draft from
    an existing diagram."""
    source = await db.execute(
        select(Diagram)
        .where(Diagram.id == source_diagram_id, Diagram.draft_id.is_(None))
        .options(selectinload(Diagram.objects))
    )
    source_diagram = source.scalar_one_or_none()
    if source_diagram is None:
        raise ValueError("Source diagram not found (or is itself a forked draft)")

    draft = await create_draft(db, draft_data, author_id=author_id)
    forked = await fork_diagram_into_draft(db, draft, source_diagram)
    return draft, forked
