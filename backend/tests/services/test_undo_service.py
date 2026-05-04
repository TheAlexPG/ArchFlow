"""Unit tests for undo_service. Each test starts with a clean DB.
Fixtures `db`, `user`, `workspace`, `diagram` come from
backend/tests/conftest.py (existing)."""
import pytest
from sqlalchemy import select

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
