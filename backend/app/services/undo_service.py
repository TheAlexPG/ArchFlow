"""Per-user undo/redo service.

See docs/superpowers/specs/2026-05-04-per-user-undo-design.md.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.undo_entry import UndoAction, UndoEntry, UndoState, UndoTargetType

COALESCE_WINDOW_SECONDS = 2
RETENTION_DAYS = 3
PER_CONTEXT_CAP = 100
MAX_SKIP_HOPS = 5  # for missing-target / Phase-2 stale cases


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


__all__ = [
    "COALESCE_WINDOW_SECONDS",
    "MAX_SKIP_HOPS",
    "PER_CONTEXT_CAP",
    "RETENTION_DAYS",
    "UndoAction",
    "UndoState",
    "UndoTargetType",
    "record",
]
