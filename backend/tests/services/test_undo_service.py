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
