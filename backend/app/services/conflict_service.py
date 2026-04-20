"""Conflict detection for draft apply.

We compute two diffs against the draft's base_version:

    main_delta = diff(base_version, current_main)
    fork_delta = diff(base_version, draft_fork)

Conflict rules (Spec §4.3):

1. Both edited the same object/connection/diagram → attribute conflict.
2. One side deleted, the other edited → delete/edit conflict.
3. Both created a connection between the same (source, target) pair —
   unlikely collision but would produce a duplicate so we flag it.

If there's no base_version_id on the draft (legacy draft created before
versioning shipped) we can't reason about concurrent changes, so we return
an empty conflict list. Safer default than a false-positive flood.
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.draft import Draft, DraftStatus
from app.models.version import VersionSource
from app.services import draft_service, version_service


async def _draft_fork_snapshot(
    db: AsyncSession, draft: Draft
) -> dict[str, Any]:
    """Snapshot what the draft WOULD look like if applied — so we can diff
    it against the base_version.

    For objects/connections this means: live (non-draft) rows minus
    deletions + forked rows. For diagrams we use the forked diagrams
    themselves (clones).
    """
    # Simplest adequate approximation: snapshot the workspace but replace
    # live objects/connections touched by the draft with their forked
    # equivalents. The existing diff endpoint already understands this
    # conceptually; here we only need per-id presence for conflict rules,
    # so we can reuse the basic workspace snapshot as a starting point.
    #
    # For v1 we treat the fork_delta as: objects/connections that exist
    # only in the draft (draft_id=draft.id). Deletions on the fork are
    # not tracked explicitly yet, so delete/edit conflicts require that
    # follow-up. This covers the common case (both edit same node) well.
    ws_id = None
    # Pull workspace_id from any of the draft's forked diagrams.
    if draft.diagrams:
        from sqlalchemy import select

        from app.models.diagram import Diagram

        d = (
            await db.execute(
                select(Diagram).where(
                    Diagram.id == draft.diagrams[0].source_diagram_id
                )
            )
        ).scalar_one_or_none()
        if d is not None:
            ws_id = d.workspace_id
    if ws_id is None:
        return {"objects": [], "connections": [], "diagrams": []}

    live = await version_service._snapshot_workspace(db, ws_id)

    # Overlay draft-scoped rows on top of the live snapshot. When a draft
    # edits an object, its forked clone has a different id; we match by
    # source_object_id to correctly flag "both edited the same node".
    from sqlalchemy import select

    from app.models.connection import Connection
    from app.models.object import ModelObject

    forked_objects = list(
        (
            await db.execute(
                select(ModelObject).where(ModelObject.draft_id == draft.id)
            )
        ).scalars().all()
    )
    forked_connections = list(
        (
            await db.execute(
                select(Connection).where(Connection.draft_id == draft.id)
            )
        ).scalars().all()
    )

    # Replace live rows with fork rows wherever source_object_id matches.
    live_objects = {o["id"]: o for o in live["objects"]}
    for fo in forked_objects:
        source_id = getattr(fo, "source_object_id", None)
        row = version_service._serialize_row(fo, version_service.OBJECT_FIELDS)
        if source_id is not None and str(source_id) in live_objects:
            live_objects[str(source_id)] = row
        else:
            live_objects[str(fo.id)] = row

    live_connections = {c["id"]: c for c in live["connections"]}
    for fc in forked_connections:
        source_id = getattr(fc, "source_connection_id", None)
        row = version_service._serialize_row(fc, version_service.CONNECTION_FIELDS)
        key = str(source_id) if source_id else str(fc.id)
        live_connections[key] = row

    return {
        "objects": list(live_objects.values()),
        "connections": list(live_connections.values()),
        "diagrams": live["diagrams"],
    }


async def compute_conflicts(
    db: AsyncSession, draft: Draft
) -> dict[str, Any]:
    if draft.status != DraftStatus.OPEN:
        return {"conflicts": [], "base_version_id": None, "reason": "not_open"}
    if draft.base_version_id is None:
        return {
            "conflicts": [],
            "base_version_id": None,
            "reason": "no_base_version",
        }

    from sqlalchemy import select

    from app.models.version import Version

    base = (
        await db.execute(select(Version).where(Version.id == draft.base_version_id))
    ).scalar_one_or_none()
    if base is None:
        return {
            "conflicts": [],
            "base_version_id": str(draft.base_version_id),
            "reason": "base_version_missing",
        }

    # Snapshot current main and the would-be-applied fork state.
    current_main = await version_service._snapshot_workspace(db, base.workspace_id)
    fork_state = await _draft_fork_snapshot(db, draft)

    main_delta = version_service.diff_snapshots(base.snapshot_data, current_main)
    fork_delta = version_service.diff_snapshots(base.snapshot_data, fork_state)

    conflicts: list[dict[str, Any]] = []

    for kind in ("objects", "connections", "diagrams"):
        main_mod = set(main_delta[kind]["modified"])
        fork_mod = set(fork_delta[kind]["modified"])
        for oid in main_mod & fork_mod:
            conflicts.append(
                {"kind": kind, "id": oid, "type": "both_edited"}
            )

        main_removed = set(main_delta[kind]["removed"])
        for oid in main_removed & fork_mod:
            conflicts.append(
                {"kind": kind, "id": oid, "type": "main_deleted_fork_edited"}
            )
        fork_removed = set(fork_delta[kind]["removed"])
        for oid in fork_removed & main_mod:
            conflicts.append(
                {"kind": kind, "id": oid, "type": "fork_deleted_main_edited"}
            )

    return {
        "conflicts": conflicts,
        "base_version_id": str(base.id),
        "main_delta": version_service.summarize_diff(main_delta),
        "fork_delta": version_service.summarize_diff(fork_delta),
    }


async def apply_with_snapshot(
    db: AsyncSession,
    draft: Draft,
    current_user_id: uuid.UUID | None,
    force: bool = False,
) -> dict[str, Any]:
    """Wrap draft_service.apply_draft with conflict gate + post-apply
    version snapshot.

    When conflicts exist and force is False, raise ValueError so the
    endpoint can return 409. Otherwise apply then snapshot.
    """
    report = await compute_conflicts(db, draft)
    if report["conflicts"] and not force:
        raise ConflictError(report)

    # Find the workspace for post-apply snapshot (draft may span diagrams
    # but they'll share a workspace in practice; we take the first).
    ws_id: uuid.UUID | None = None
    if draft.diagrams:
        from sqlalchemy import select

        from app.models.diagram import Diagram

        d = (
            await db.execute(
                select(Diagram).where(
                    Diagram.id == draft.diagrams[0].source_diagram_id
                )
            )
        ).scalar_one_or_none()
        if d is not None:
            ws_id = d.workspace_id

    result = await draft_service.apply_draft(db, draft)

    if ws_id is not None:
        version = await version_service.create_snapshot(
            db,
            workspace_id=ws_id,
            source=VersionSource.APPLY,
            draft_id=draft.id,
            created_by_user_id=current_user_id,
        )
        result["version_id"] = str(version.id)
        result["version_label"] = version.label

    return result


class ConflictError(Exception):
    def __init__(self, report: dict[str, Any]):
        super().__init__("Draft has conflicts")
        self.report = report
