"""Unit tests for undo_service. Each test starts with a clean DB.
Fixtures `db`, `user`, `workspace`, `diagram` come from
backend/tests/conftest.py (existing)."""
import pytest
from sqlalchemy import select

from app.models.object import ModelObject
from app.models.undo_entry import UndoAction, UndoEntry, UndoState, UndoTargetType
from app.services import undo_service


@pytest.mark.asyncio
async def test_record_creates_entry(db, user, workspace, diagram):
    entry = await undo_service.record(
        db,
        user_id=user.id,
        workspace_id=workspace.id,
        diagram_id=diagram.id,
        draft_id=None,
        target_type=UndoTargetType.OBJECT,
        target_id=diagram.id,
        action=UndoAction.UPDATE,
        forward_summary="Renamed Foo -> Bar",
        inverse_payload={"before": {"name": "Foo"}},
        after_state={"name": "Bar"},
        coalesce_key="object:abc:name",
    )
    await db.commit()
    assert entry.id is not None
    assert entry.seq == 1
    assert entry.state == UndoState.ACTIVE
    assert entry.inverse_payload == {"before": {"name": "Foo"}}


@pytest.mark.asyncio
async def test_record_coalesces_within_window(db, user, workspace, diagram):
    e1 = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="P",
        inverse_payload={"before": {"name": ""}},
        coalesce_key="object:abc:name",
        after_state={"name": "P"},
    )
    e2 = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="Pa",
        inverse_payload={"before": {"name": "P"}},
        coalesce_key="object:abc:name",
        after_state={"name": "Pa"},
    )
    await db.commit()
    assert e1.id == e2.id
    assert e2.inverse_payload == {"before": {"name": ""}}  # kept from FIRST record
    assert e2.forward_summary == "Pa"
    assert e2.after_state == {"name": "Pa"}


@pytest.mark.asyncio
async def test_record_does_not_coalesce_different_field(db, user, workspace, diagram):
    e1 = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="rename",
        inverse_payload={}, coalesce_key="object:abc:name",
    )
    e2 = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="status",
        inverse_payload={}, coalesce_key="object:abc:status",
    )
    assert e1.id != e2.id
    assert e2.seq == e1.seq + 1


@pytest.mark.asyncio
async def test_record_does_not_coalesce_different_user(
    db, user, user_other, workspace, diagram
):
    e1 = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="x",
        inverse_payload={}, coalesce_key="object:abc:name",
    )
    e2 = await undo_service.record(
        db, user_id=user_other.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="x",
        inverse_payload={}, coalesce_key="object:abc:name",
    )
    assert e1.id != e2.id


@pytest.mark.asyncio
async def test_record_evicts_beyond_cap(db, user, workspace, diagram, monkeypatch):
    monkeypatch.setattr(undo_service, "PER_CONTEXT_CAP", 3)
    ids = []
    for i in range(5):
        e = await undo_service.record(
            db, user_id=user.id, workspace_id=workspace.id,
            diagram_id=diagram.id, draft_id=None,
            target_type=UndoTargetType.OBJECT, target_id=diagram.id,
            action=UndoAction.UPDATE, forward_summary=f"a{i}",
            inverse_payload={}, coalesce_key=f"object:abc:f{i}",
        )
        ids.append(e.id)
    surviving = (await db.execute(
        select(UndoEntry.id).where(UndoEntry.user_id == user.id)
    )).scalars().all()
    assert set(surviving) == set(ids[-3:])


@pytest.mark.asyncio
async def test_undo_update_restores_previous_value(
    db, user, workspace, diagram
):
    obj = ModelObject(name="After", type="system", workspace_id=workspace.id)
    db.add(obj)
    await db.flush()

    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=obj.id,
        action=UndoAction.UPDATE,
        forward_summary="Renamed Before -> After",
        inverse_payload={"before": {"name": "Before"}},
        after_state={"name": "After"},
        coalesce_key=f"object:{obj.id}:name",
    )

    res = await undo_service.undo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )

    await db.refresh(obj)
    assert obj.name == "Before"
    assert res.undone_entry.state == UndoState.UNDONE
    assert res.undone_entry.redo_payload == {"name": "After"}


@pytest.mark.asyncio
async def test_redo_after_undo_restores_after_state(db, user, workspace, diagram):
    obj = ModelObject(name="After", type="system", workspace_id=workspace.id)
    db.add(obj)
    await db.flush()

    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=obj.id,
        action=UndoAction.UPDATE,
        forward_summary="Renamed Before -> After",
        inverse_payload={"before": {"name": "Before"}},
        after_state={"name": "After"},
        coalesce_key=f"object:{obj.id}:name",
    )
    await undo_service.undo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )
    await db.refresh(obj)
    assert obj.name == "Before"

    await undo_service.redo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )
    await db.refresh(obj)
    assert obj.name == "After"


@pytest.mark.asyncio
async def test_redo_uses_current_state_not_pre_undo_state(
    db, user, workspace, diagram
):
    """Figma's trick: if Bob changed the value between Alice's edit and
    Alice's undo, redo should land at *current* (Bob's) value, not Alice's
    original after-value."""
    obj = ModelObject(name="Alice's value", type="system",
                       workspace_id=workspace.id)
    db.add(obj)
    await db.flush()

    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=obj.id,
        action=UndoAction.UPDATE,
        forward_summary="Alice rename",
        inverse_payload={"before": {"name": "Original"}},
        after_state={"name": "Alice's value"},
        coalesce_key=f"object:{obj.id}:name",
    )

    obj.name = "Bob's value"  # Bob's change between Alice's edit and undo
    await db.flush()

    await undo_service.undo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )
    await db.refresh(obj)
    assert obj.name == "Original"

    await undo_service.redo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )
    await db.refresh(obj)
    assert obj.name == "Bob's value"  # NOT "Alice's value"


@pytest.mark.asyncio
async def test_undo_skips_when_target_missing(db, user, workspace, diagram):
    obj = ModelObject(name="A", type="system", workspace_id=workspace.id)
    db.add(obj)
    await db.flush()
    obj_id = obj.id

    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=obj_id,
        action=UndoAction.UPDATE,
        forward_summary="rename",
        inverse_payload={"before": {"name": "B"}},
        coalesce_key=f"object:{obj_id}:name",
    )
    await db.delete(obj)
    await db.flush()

    res = await undo_service.undo(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user,
    )
    assert res.remaining_undo_count == 0
    skipped = (await db.execute(
        select(UndoEntry).where(UndoEntry.target_id == obj_id)
    )).scalar_one()
    assert skipped.state == UndoState.SKIPPED


from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_history_returns_entries_in_reverse_seq_order(
    db, user, workspace, diagram
):
    for i in range(3):
        await undo_service.record(
            db, user_id=user.id, workspace_id=workspace.id,
            diagram_id=diagram.id, draft_id=None,
            target_type=UndoTargetType.OBJECT, target_id=diagram.id,
            action=UndoAction.UPDATE,
            forward_summary=f"a{i}",
            inverse_payload={}, coalesce_key=f"k{i}",
        )
    h = await undo_service.history(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None, limit=10,
    )
    assert [e.forward_summary for e in h.entries] == ["a2", "a1", "a0"]
    assert h.cursor_seq == 3


@pytest.mark.asyncio
async def test_history_excludes_entries_older_than_retention(
    db, user, workspace, diagram
):
    e = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE,
        forward_summary="ancient",
        inverse_payload={}, coalesce_key="k",
    )
    e.created_at = datetime.now(timezone.utc) - timedelta(days=4)
    await db.flush()

    h = await undo_service.history(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None, limit=10,
    )
    assert h.entries == []


@pytest.mark.asyncio
async def test_undo_to_walks_back_three_steps(db, user, workspace, diagram):
    objs = []
    for n in ("A", "B", "C"):
        o = ModelObject(name=n, type="system", workspace_id=workspace.id)
        db.add(o); await db.flush(); objs.append(o)
        await undo_service.record(
            db, user_id=user.id, workspace_id=workspace.id,
            diagram_id=diagram.id, draft_id=None,
            target_type=UndoTargetType.OBJECT, target_id=o.id,
            action=UndoAction.UPDATE,
            forward_summary=f"Renamed something to {n}",
            inverse_payload={"before": {"name": "old"}},
            after_state={"name": n},
            coalesce_key=f"object:{o.id}:name",
        )
    # Find the entry that targets `objs[0]` (the "A" entry — oldest).
    target_entry = (await db.execute(
        select(UndoEntry).where(UndoEntry.target_id == objs[0].id)
    )).scalar_one()

    res = await undo_service.undo_to(
        db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
        actor_user=user, entry_id=target_entry.id,
    )
    assert len(res.applied) == 3
    for o in objs:
        await db.refresh(o)
        assert o.name == "old"


@pytest.mark.asyncio
async def test_undo_to_rejects_other_users_entry(db, user, user_other, workspace, diagram):
    """Auth guard: undo_to(entry_id from another user) raises UndoEntryNotFound."""
    o = ModelObject(name="X", type="system", workspace_id=workspace.id)
    db.add(o); await db.flush()
    other_entry = await undo_service.record(
        db, user_id=user_other.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=o.id,
        action=UndoAction.UPDATE,
        forward_summary="other user's edit",
        inverse_payload={"before": {"name": "old"}},
        after_state={"name": "X"},
        coalesce_key=f"object:{o.id}:name",
    )
    with pytest.raises(undo_service.UndoEntryNotFound):
        await undo_service.undo_to(
            db, user_id=user.id, diagram_id=diagram.id, draft_id=None,
            actor_user=user, entry_id=other_entry.id,
        )


@pytest.mark.asyncio
async def test_undo_to_rejects_cross_draft_entry(db, user, workspace, diagram):
    """Auth guard: a draft entry can't be reached from a live (draft_id=None) call."""
    import uuid as _uuid
    fake_draft_id = _uuid.uuid4()
    # Insert a row directly so we don't have to fixture a real Draft row;
    # we only need the FK to exist for the lookup. We bypass record() because
    # we're not testing record(), we're testing the auth guard.
    o = ModelObject(name="Y", type="system", workspace_id=workspace.id)
    db.add(o); await db.flush()
    # We can't easily insert a draft_id without a real Draft row (FK).
    # Instead, record an entry under draft_id=None, then hand-set draft_id
    # on the row to a real-looking UUID just for this guard check.
    entry = await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=o.id,
        action=UndoAction.UPDATE,
        forward_summary="live edit",
        inverse_payload={"before": {"name": "old"}},
        after_state={"name": "Y"},
        coalesce_key=f"object:{o.id}:name",
    )
    # Simulate the cross-context case: caller passes a real draft_id but
    # the entry belongs to live (draft_id=None).
    with pytest.raises(undo_service.UndoEntryNotFound):
        await undo_service.undo_to(
            db, user_id=user.id, diagram_id=diagram.id,
            draft_id=fake_draft_id,  # caller context = some draft
            actor_user=user, entry_id=entry.id,  # entry context = live
        )


@pytest.mark.asyncio
async def test_discarding_draft_drops_its_undo_entries(db, user, workspace, diagram):
    """When a draft is discarded, all undo entries scoped to that draft are
    hard-deleted. Live-stack entries (draft_id IS NULL) are untouched."""
    from app.models.draft import Draft, DraftStatus
    from app.services import draft_service

    draft = Draft(
        name="Test Draft",
        status=DraftStatus.OPEN,
        author_id=user.id,
    )
    db.add(draft)
    await db.flush()

    # One draft-scoped entry, one live entry (draft_id=None).
    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=draft.id,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="draft edit",
        inverse_payload={}, coalesce_key=f"object:{diagram.id}:draft",
    )
    await undo_service.record(
        db, user_id=user.id, workspace_id=workspace.id,
        diagram_id=diagram.id, draft_id=None,
        target_type=UndoTargetType.OBJECT, target_id=diagram.id,
        action=UndoAction.UPDATE, forward_summary="live edit",
        inverse_payload={}, coalesce_key=f"object:{diagram.id}:live",
    )
    await db.flush()

    await draft_service.discard_draft(db, draft)
    await db.flush()

    rows = (await db.execute(
        select(UndoEntry).where(UndoEntry.diagram_id == diagram.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].draft_id is None
