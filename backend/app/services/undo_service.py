"""Per-user undo/redo service.

See docs/superpowers/specs/2026-05-04-per-user-undo-design.md.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.diagram import DiagramObject
from app.models.object import ModelObject
from app.models.undo_entry import UndoAction, UndoEntry, UndoState, UndoTargetType
from app.services import restore_service

COALESCE_WINDOW_SECONDS = 2
RETENTION_DAYS = 3
PER_CONTEXT_CAP = 100
MAX_SKIP_HOPS = 5  # for missing-target / Phase-2 stale cases

# Multi-target operations (a multi-object drag, drop, or delete) fire many
# per-target mutations within milliseconds of each other. They produce
# distinct undo entries (one per target_id), but the user thinks of them
# as one logical action — pressing Cmd+Z should revert the whole burst.
# We detect these at undo/redo time by created_at proximity + same
# target_type + same coalesce-key kind (the trailing segment, e.g.
# 'position', 'size', 'create'). Window is tight to avoid sweeping in
# unrelated edits; intentional sequential edits are >150ms apart.
BURST_WINDOW_SECONDS = 0.15


def _coalesce_kind(key: str) -> str:
    """Last colon-separated segment of a coalesce_key.

    `'diagram_object:abc:position'` → `'position'`
    `'object:abc:create'` → `'create'`
    Used to group burst peers by operation kind without grouping a
    position drag with a size resize that happened to land in the same
    millisecond window.
    """
    return key.rsplit(":", 1)[-1]


async def record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    target_type: UndoTargetType,
    target_id: uuid.UUID,
    action: UndoAction,
    forward_summary: str,
    inverse_payload: dict,
    coalesce_key: str,
    after_state: dict | None = None,
) -> UndoEntry:
    """Record an undo entry. Coalesces with a recent same-key entry from the
    same user/context if within COALESCE_WINDOW_SECONDS. Otherwise inserts a
    new entry and evicts the oldest beyond PER_CONTEXT_CAP. Also clears any
    `state='undone'` redo entries for this context (a new action invalidates
    redo)."""
    await _clear_redo(db, user_id, diagram_id, draft_id)

    coalesced = await _try_coalesce(
        db,
        user_id,
        diagram_id,
        draft_id,
        coalesce_key,
        forward_summary,
        after_state,
    )
    if coalesced is not None:
        return coalesced

    next_seq = await _next_seq(db, user_id, diagram_id, draft_id)
    entry = UndoEntry(
        workspace_id=workspace_id,
        user_id=user_id,
        diagram_id=diagram_id,
        draft_id=draft_id,
        seq=next_seq,
        target_type=target_type,
        target_id=target_id,
        action=action,
        forward_summary=forward_summary,
        inverse_payload=inverse_payload,
        after_state=after_state,
        coalesce_key=coalesce_key,
        state=UndoState.ACTIVE,
    )
    db.add(entry)
    await db.flush()

    await _enforce_cap(db, user_id, diagram_id, draft_id)
    return entry


async def _clear_redo(
    db: AsyncSession,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
) -> None:
    await db.execute(
        delete(UndoEntry).where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
            UndoEntry.state == UndoState.UNDONE,
        )
    )


async def _try_coalesce(
    db: AsyncSession,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    coalesce_key: str,
    forward_summary: str,
    after_state: dict | None,
) -> UndoEntry | None:
    cutoff = datetime.now(UTC) - timedelta(seconds=COALESCE_WINDOW_SECONDS)
    q = (
        select(UndoEntry)
        .where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
            UndoEntry.coalesce_key == coalesce_key,
            UndoEntry.state == UndoState.ACTIVE,
            UndoEntry.updated_at > cutoff,
        )
        .order_by(UndoEntry.seq.desc())
        .limit(1)
    )
    res = await db.execute(q)
    recent = res.scalar_one_or_none()
    if recent is None:
        return None
    # Merge: keep recent.inverse_payload (= state before the FIRST edit in
    # the window), update updated_at + forward_summary + after_state to
    # reflect the latest change.
    recent.updated_at = datetime.now(UTC)
    recent.forward_summary = forward_summary
    if after_state is not None:
        recent.after_state = after_state
    await db.flush()
    return recent


async def _next_seq(
    db: AsyncSession,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
) -> int:
    q = select(func.coalesce(func.max(UndoEntry.seq), 0)).where(
        UndoEntry.user_id == user_id,
        UndoEntry.diagram_id == diagram_id,
        _draft_eq(draft_id),
    )
    res = await db.execute(q)
    return int(res.scalar_one()) + 1


async def _enforce_cap(
    db: AsyncSession,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
) -> None:
    sub = (
        select(UndoEntry.id)
        .where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
        )
        .order_by(UndoEntry.seq.desc())
        .offset(PER_CONTEXT_CAP)
    ).scalar_subquery()
    await db.execute(delete(UndoEntry).where(UndoEntry.id.in_(sub)))


def _draft_eq(draft_id: uuid.UUID | None):
    """Generate a `draft_id IS NULL` or `draft_id = :did` predicate."""
    if draft_id is None:
        return UndoEntry.draft_id.is_(None)
    return UndoEntry.draft_id == draft_id


class UndoStackEmpty(Exception):
    ...


class UndoConcurrencyError(Exception):
    def __init__(self, actual_seq: int):
        self.actual_seq = actual_seq


class UndoTargetMissing(Exception):
    def __init__(self, entry):
        self.entry = entry


@dataclass
class UndoResult:
    undone_entry: UndoEntry | None
    redone_entry: UndoEntry | None
    cursor_seq: int | None
    remaining_undo_count: int
    redo_count: int


async def _undo_single(db, entry: UndoEntry, actor_user) -> bool:
    """Apply the inverse of one entry and update its state.

    Returns True on success (entry → UNDONE), False if the target row was
    missing (entry → SKIPPED). Captures redo_payload using the Figma
    snapshot trick. Caller handles transactional commit.
    """
    current = await _snapshot_target(db, entry.target_type, entry.target_id)
    if entry.action == UndoAction.UPDATE:
        before = entry.inverse_payload.get("before") or {}
        entry.redo_payload = {k: current.get(k) for k in before}
    else:
        entry.redo_payload = current

    try:
        await _apply(
            db, entry, payload=entry.inverse_payload,
            actor_user=actor_user, direction="undo",
        )
    except UndoTargetMissing:
        entry.state = UndoState.SKIPPED
        entry.undone_at = datetime.now(UTC)
        await db.flush()
        return False

    entry.state = UndoState.UNDONE
    entry.undone_at = datetime.now(UTC)
    await db.flush()
    return True


async def undo(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    actor_user,
    expected_seq: int | None = None,
    hops_remaining: int = MAX_SKIP_HOPS,
    burst_floor_seq: int | None = None,
) -> UndoResult:
    """Undo the top active entry. Bursts peer entries from the same logical
    multi-target operation (see BURST_WINDOW_SECONDS).

    `burst_floor_seq` caps how far the burst loop will walk down the stack;
    used by `undo_to` to prevent bursting past the user's chosen target.
    """
    entry = await _top_active(db, user_id, diagram_id, draft_id)
    if entry is None:
        raise UndoStackEmpty()
    if expected_seq is not None and entry.seq != expected_seq:
        raise UndoConcurrencyError(actual_seq=entry.seq)

    success = await _undo_single(db, entry, actor_user)
    if not success:
        # Skip-on-missing recursion: try the next entry down. Bound by
        # MAX_SKIP_HOPS so we don't unwind the entire stack on a corrupted
        # entry chain.
        if hops_remaining <= 0:
            return await _stack_summary(
                db, user_id, diagram_id, draft_id,
                undone=entry, redone=None,
            )
        try:
            return await undo(
                db, user_id=user_id, diagram_id=diagram_id, draft_id=draft_id,
                actor_user=actor_user, expected_seq=None,
                hops_remaining=hops_remaining - 1,
            )
        except UndoStackEmpty:
            return await _stack_summary(
                db, user_id, diagram_id, draft_id,
                undone=entry, redone=None,
            )

    # Burst-undo: a multi-target operation (e.g. dragging 3 selected
    # objects) fires per-target mutations in tight succession, each
    # producing a separate undo entry. Pulling back peer entries that
    # share the operation kind and were created within BURST_WINDOW_SECONDS
    # makes a single Cmd+Z revert the whole logical action.
    anchor_kind = _coalesce_kind(entry.coalesce_key)
    anchor_target_type = entry.target_type
    anchor_time = entry.created_at
    while True:
        peer = await _top_active(db, user_id, diagram_id, draft_id)
        if peer is None:
            break
        if (
            peer.target_type != anchor_target_type
            or _coalesce_kind(peer.coalesce_key) != anchor_kind
        ):
            break
        if burst_floor_seq is not None and peer.seq < burst_floor_seq:
            break
        gap = (anchor_time - peer.created_at).total_seconds()
        if gap < 0 or gap > BURST_WINDOW_SECONDS:
            break
        await _undo_single(db, peer, actor_user)
        anchor_time = peer.created_at  # extend window from each peer

    return await _stack_summary(
        db, user_id, diagram_id, draft_id,
        undone=entry, redone=None,
    )


async def redo(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    actor_user,
    expected_seq: int | None = None,
    burst_ceiling_seq: int | None = None,
) -> UndoResult:
    """Redo the next undone entry (smallest undone seq). Bursts peer entries
    when they look like a multi-target operation.

    `burst_ceiling_seq` caps how far up the burst will walk; used by
    `undo_to` so the user's chosen target seq remains the new top.
    """
    entry = await _top_undone(db, user_id, diagram_id, draft_id)
    if entry is None:
        raise UndoStackEmpty()
    if expected_seq is not None and entry.seq != expected_seq:
        raise UndoConcurrencyError(actual_seq=entry.seq)

    await _redo_single(db, entry, actor_user)

    # Burst-redo: mirror burst-undo so a multi-target operation that was
    # bursted on undo also bursts on redo. Walk peers (next undone entries)
    # within the burst window that share the same operation kind.
    anchor_kind = _coalesce_kind(entry.coalesce_key)
    anchor_target_type = entry.target_type
    anchor_time = entry.created_at
    while True:
        peer = await _top_undone(db, user_id, diagram_id, draft_id)
        if peer is None:
            break
        if (
            peer.target_type != anchor_target_type
            or _coalesce_kind(peer.coalesce_key) != anchor_kind
        ):
            break
        if burst_ceiling_seq is not None and peer.seq > burst_ceiling_seq:
            break
        gap = abs((peer.created_at - anchor_time).total_seconds())
        if gap > BURST_WINDOW_SECONDS:
            break
        await _redo_single(db, peer, actor_user)
        anchor_time = peer.created_at

    return await _stack_summary(
        db, user_id, diagram_id, draft_id,
        undone=None, redone=entry,
    )


async def _redo_single(db, entry: UndoEntry, actor_user) -> None:
    """Re-apply one entry's after-state and flip it back to ACTIVE."""
    if entry.redo_payload is None:
        raise RuntimeError(f"Undone entry {entry.id} has no redo_payload")
    await _apply(
        db, entry, payload={"after": entry.redo_payload},
        actor_user=actor_user, direction="redo",
    )
    entry.state = UndoState.ACTIVE
    entry.undone_at = None
    await db.flush()


async def _top_active(db, user_id, diagram_id, draft_id):
    q = (
        select(UndoEntry)
        .where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
            UndoEntry.state == UndoState.ACTIVE,
            UndoEntry.created_at > _retention_cutoff(),
        )
        .order_by(UndoEntry.seq.desc()).limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _top_undone(db, user_id, diagram_id, draft_id):
    """Smallest undone seq = the most recent undo, the next to redo."""
    q = (
        select(UndoEntry)
        .where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
            UndoEntry.state == UndoState.UNDONE,
        )
        .order_by(UndoEntry.seq.asc()).limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


def _retention_cutoff():
    return datetime.now(UTC) - timedelta(days=RETENTION_DAYS)


async def _snapshot_target(
    db: AsyncSession, target_type: UndoTargetType, target_id: uuid.UUID
) -> dict:
    """Snapshot user-visible fields of a target. Reuses
    activity_service._snapshot for consistency with the audit log."""
    from app.services import activity_service

    if target_type == UndoTargetType.OBJECT:
        obj = await db.get(ModelObject, target_id)
    elif target_type == UndoTargetType.CONNECTION:
        obj = await db.get(Connection, target_id)
    elif target_type == UndoTargetType.DIAGRAM_OBJECT:
        obj = await db.get(DiagramObject, target_id)
    elif target_type == UndoTargetType.COMMENT:
        from app.models.comment import Comment

        obj = await db.get(Comment, target_id)
    else:
        obj = None  # edge_property folded into connection
    if obj is None:
        return {}
    return activity_service._snapshot(obj)


async def _apply(db, entry: UndoEntry, *, payload: dict, actor_user, direction: str):
    if entry.action == UndoAction.UPDATE:
        await _apply_update(db, entry, payload)
    elif entry.action == UndoAction.CREATE:
        if direction == "undo":
            await _apply_delete(db, entry)
        else:
            await _apply_restore(db, entry, payload)
    elif entry.action == UndoAction.DELETE:
        if direction == "undo":
            await _apply_restore(db, entry, payload)
        else:
            await _apply_delete(db, entry)


async def _apply_update(db, entry, payload):
    target = await _load_target(db, entry.target_type, entry.target_id)
    if target is None:
        raise UndoTargetMissing(entry)
    fields = payload.get("before") or payload.get("after") or {}
    for field, value in fields.items():
        setattr(target, field, value)
    await db.flush()


async def _apply_delete(db, entry):
    target = await _load_target(db, entry.target_type, entry.target_id)
    if target is None:
        raise UndoTargetMissing(entry)
    await db.delete(target)
    await db.flush()


async def _apply_restore(db, entry, payload):
    snapshot = entry.inverse_payload.get("snapshot") or payload.get("after")
    if snapshot is None:
        raise RuntimeError(
            f"Cannot restore entry {entry.id}: no snapshot in inverse_payload"
        )
    await restore_service.restore(
        db, target_type=entry.target_type,
        target_id=entry.target_id, snapshot=snapshot,
    )


async def _load_target(db, target_type: UndoTargetType, target_id: uuid.UUID):
    if target_type == UndoTargetType.OBJECT:
        return await db.get(ModelObject, target_id)
    if target_type == UndoTargetType.CONNECTION:
        return await db.get(Connection, target_id)
    if target_type == UndoTargetType.DIAGRAM_OBJECT:
        return await db.get(DiagramObject, target_id)
    if target_type == UndoTargetType.COMMENT:
        from app.models.comment import Comment

        return await db.get(Comment, target_id)
    return None


async def _stack_summary(
    db, user_id, diagram_id, draft_id, *,
    undone: UndoEntry | None, redone: UndoEntry | None,
) -> UndoResult:
    cursor_q = select(func.max(UndoEntry.seq)).where(
        UndoEntry.user_id == user_id,
        UndoEntry.diagram_id == diagram_id,
        _draft_eq(draft_id),
        UndoEntry.state == UndoState.ACTIVE,
        UndoEntry.created_at > _retention_cutoff(),
    )
    cursor_seq = (await db.execute(cursor_q)).scalar()

    counts_q = select(UndoEntry.state, func.count()).where(
        UndoEntry.user_id == user_id,
        UndoEntry.diagram_id == diagram_id,
        _draft_eq(draft_id),
        UndoEntry.created_at > _retention_cutoff(),
    ).group_by(UndoEntry.state)
    counts = {state: n for state, n in (await db.execute(counts_q)).all()}

    return UndoResult(
        undone_entry=undone,
        redone_entry=redone,
        cursor_seq=cursor_seq,
        remaining_undo_count=counts.get(UndoState.ACTIVE, 0),
        redo_count=counts.get(UndoState.UNDONE, 0),
    )


@dataclass
class UndoHistory:
    entries: list[UndoEntry]
    cursor_seq: int | None


async def history(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    limit: int = 50,
) -> UndoHistory:
    q = (
        select(UndoEntry)
        .where(
            UndoEntry.user_id == user_id,
            UndoEntry.diagram_id == diagram_id,
            _draft_eq(draft_id),
            UndoEntry.created_at > _retention_cutoff(),
        )
        .order_by(UndoEntry.seq.desc())
        .limit(limit)
    )
    entries = list((await db.execute(q)).scalars().all())

    cursor_q = select(func.max(UndoEntry.seq)).where(
        UndoEntry.user_id == user_id,
        UndoEntry.diagram_id == diagram_id,
        _draft_eq(draft_id),
        UndoEntry.state == UndoState.ACTIVE,
        UndoEntry.created_at > _retention_cutoff(),
    )
    cursor_seq = (await db.execute(cursor_q)).scalar()

    return UndoHistory(entries=entries, cursor_seq=cursor_seq)


async def sweep_old_entries(db: AsyncSession) -> int:
    """Hard-delete rows older than RETENTION_DAYS. Intended for a daily job.
    Returns rows deleted."""
    cutoff = _retention_cutoff()
    result = await db.execute(
        delete(UndoEntry).where(UndoEntry.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount or 0


@dataclass
class UndoToResult:
    applied: list[dict]
    cursor_seq: int | None


class UndoEntryNotFound(Exception): ...


async def undo_to(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    diagram_id: uuid.UUID,
    draft_id: uuid.UUID | None,
    actor_user,
    entry_id: uuid.UUID,
    expected_path_length: int | None = None,
) -> UndoToResult:
    """Undo or redo until `entry_id` is itself the last operation applied
    (i.e. the target entry is also undone/redone — matching the
    Figma/Excalidraw history-popover semantic of 'roll back to before X').
    Atomic — runs in the existing transaction; the caller commits.
    """
    target = await db.get(UndoEntry, entry_id)
    if (
        target is None
        or target.user_id != user_id
        or target.diagram_id != diagram_id
        or target.draft_id != draft_id
    ):
        raise UndoEntryNotFound()

    # SKIPPED entries are not reachable: _redo_until only finds UNDONE rows,
    # so it would silently over-redo without ever stopping at the target.
    if target.state == UndoState.SKIPPED:
        raise UndoEntryNotFound()

    if target.state == UndoState.ACTIVE:
        applied = await _undo_until(db, user_id, diagram_id, draft_id,
                                     target.seq, actor_user)
    else:  # UNDONE
        applied = await _redo_until(db, user_id, diagram_id, draft_id,
                                     target.seq, actor_user)

    summary = await _stack_summary(db, user_id, diagram_id, draft_id,
                                   undone=None, redone=None)

    if expected_path_length is not None and len(applied) != expected_path_length:
        # actual_seq returns the current cursor (top of active stack) so the
        # client can sync its state — same contract as /undo and /redo 409s.
        # Falls back to target.seq if the stack is empty post-walk.
        raise UndoConcurrencyError(actual_seq=summary.cursor_seq or target.seq)

    return UndoToResult(applied=applied, cursor_seq=summary.cursor_seq)


async def _undo_until(db, user_id, diagram_id, draft_id, target_seq, actor_user):
    """Undo entries from the top of the active stack down to and including
    target_seq. Stop condition is `top.seq < target_seq` (strict) so that the
    target entry itself is also undone — see test_undo_to_walks_back_three_steps.
    This matches the Figma UX of 'click entry X → roll back to state before X'.
    """
    applied = []
    while True:
        top = await _top_active(db, user_id, diagram_id, draft_id)
        if top is None or top.seq < target_seq:
            return applied
        await undo(
            db, user_id=user_id, diagram_id=diagram_id, draft_id=draft_id,
            actor_user=actor_user,
            # Cap the burst loop so it doesn't undo past the user's chosen
            # target. Without this, a temporally-tight sequence of edits
            # straddling target_seq could be wholly bursted in one undo()
            # call.
            burst_floor_seq=target_seq,
        )
        applied.append({"entry_id": str(top.id), "direction": "undo"})


async def _redo_until(db, user_id, diagram_id, draft_id, target_seq, actor_user):
    """Redo undone entries from bottom-up until target_seq is the new active top.
    `_top_undone` returns the smallest undone seq (= oldest undo, first to redo).
    Stop when top.seq > target_seq so target ends up ACTIVE at the top of the
    stack — see test_undo_to_walks_back_three_steps.
    """
    applied = []
    while True:
        top = await _top_undone(db, user_id, diagram_id, draft_id)
        if top is None or top.seq > target_seq:
            return applied
        await redo(
            db, user_id=user_id, diagram_id=diagram_id, draft_id=draft_id,
            actor_user=actor_user,
            # Cap burst to target_seq so a fast-fired redo burst can't
            # leapfrog past the user's chosen point.
            burst_ceiling_seq=target_seq,
        )
        applied.append({"entry_id": str(top.id), "direction": "redo"})


__all__ = [
    "COALESCE_WINDOW_SECONDS",
    "MAX_SKIP_HOPS",
    "PER_CONTEXT_CAP",
    "RETENTION_DAYS",
    "UndoAction",
    "UndoConcurrencyError",
    "UndoEntryNotFound",
    "UndoHistory",
    "UndoResult",
    "UndoStackEmpty",
    "UndoState",
    "UndoTargetMissing",
    "UndoTargetType",
    "UndoToResult",
    "history",
    "record",
    "redo",
    "sweep_old_entries",
    "undo",
    "undo_to",
]
