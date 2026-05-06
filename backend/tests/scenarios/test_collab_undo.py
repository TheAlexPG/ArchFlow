"""Multi-user collaboration scenario tests for per-user undo.

Tests 1 and 2 are service-level (use ``db`` / ``user`` / ``user_other``
fixtures from conftest.py — no HTTP).

Test 3 is HTTP-only (uses the ``client`` fixture + the same ``_register``
pattern from test_undo_endpoints.py) so there is no cross-session
data-visibility problem.

Test 4 is a skipped Phase-2 placeholder.
"""
import asyncio
import uuid

import pytest

from app.core.database import async_session


# ─── Helpers (HTTP tests) ────────────────────────────────────────────────────


async def _register(client, tag: str = "u") -> tuple[str, str, str]:
    """Register a fresh user. Returns (token, email, workspace_id)."""
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": f"{tag.title()} Tester", "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    ws = (
        await client.get(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()[0]
    return token, email, ws["id"]


async def _create_diagram(client, token: str, ws_id: str, name: str = "Collab Diag") -> str:
    """Create a diagram via HTTP and return its id string."""
    r = await client.post(
        "/api/v1/diagrams",
        json={"name": name, "type": "system_landscape"},
        headers={"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Test 1 — LWW lock-in ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alice_undo_overwrites_bob_in_phase1(
    db, user, user_other, workspace, diagram,
):
    """Phase 1 deliberately uses last-write-wins. Lock this in so a future
    Phase 2 enable doesn't silently regress it.

    Sequence:
      1. Alice renames the object to "Alice's value".
      2. Bob renames it to "Bob's value".
      3. Alice undoes → object name reverts to "Original" (overwrites Bob's value).
    """
    from app.models.object import ModelObject, ObjectType
    from app.schemas.object import ObjectUpdate
    from app.services import object_service, undo_service

    # Seed the shared object
    obj = ModelObject(
        name="Original",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add(obj)
    await db.flush()

    # Alice renames it
    await object_service.update_object(
        db,
        obj,
        ObjectUpdate(name="Alice's value"),
        actor_user=user,
        from_diagram_id=diagram.id,
    )

    # Bob renames it
    await object_service.update_object(
        db,
        obj,
        ObjectUpdate(name="Bob's value"),
        actor_user=user_other,
        from_diagram_id=diagram.id,
    )

    # Alice undoes (user = alice)
    await undo_service.undo(
        db,
        user_id=user.id,
        diagram_id=diagram.id,
        draft_id=None,
        actor_user=user,
    )

    await db.refresh(obj)
    # Phase 1 LWW: Alice's undo writes "Original" back, clobbering Bob's value.
    assert obj.name == "Original", (
        f"Expected 'Original' (LWW), got {obj.name!r}"
    )


# ─── Test 2 — delete-undo same UUID ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_alice_undo_recreates_deleted_object_with_same_uuid(
    db, user, workspace, diagram,
):
    """Undo of a delete must recreate the row with the original UUID so that
    other diagrams referencing the same object ID keep working."""
    from app.models.object import ModelObject, ObjectType
    from app.services import object_service, undo_service

    obj = ModelObject(
        name="X",
        type=ObjectType.SYSTEM,
        workspace_id=workspace.id,
    )
    db.add(obj)
    await db.flush()
    obj_id = obj.id

    # Alice deletes the object
    await object_service.delete_object(
        db,
        obj,
        actor_user=user,
        from_diagram_id=diagram.id,
    )

    # Verify it's gone
    assert (await db.get(ModelObject, obj_id)) is None

    # Alice undoes the delete
    await undo_service.undo(
        db,
        user_id=user.id,
        diagram_id=diagram.id,
        draft_id=None,
        actor_user=user,
    )

    restored = await db.get(ModelObject, obj_id)
    assert restored is not None, "Object was not restored after undo"
    assert restored.id == obj_id, "Restored object has a different UUID"
    assert restored.name == "X", f"Expected name 'X', got {restored.name!r}"


# ─── Test 3 — concurrent /undo race ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_undo_first_wins_second_409s(client):
    """Two POST /undo requests with the same stale expected_seq must resolve
    to [200, 409] — one wins, one loses due to seq mismatch.

    This simulates two browser tabs opened at the same time: both think the
    top of the stack is seq=2, but after the first tab's undo lands the top
    is seq=1.  The second tab sends expected_seq=2, which no longer matches
    the actual top (seq=1), yielding 409.

    Note: with the in-process ASGI transport these run sequentially in the
    same event loop, so we simulate the race by sending requests in two
    batches: first request wins, second is sent with the now-stale seq.
    asyncio.gather fires them "concurrently" but they are serialised by the
    single-threaded event loop — the important assertion is that the endpoint
    correctly detects the stale seq and rejects the second attempt.
    """
    from app.models.diagram import Diagram
    from app.models.undo_entry import UndoAction, UndoEntry, UndoState, UndoTargetType
    from sqlalchemy import select

    # Register a fresh user and create a diagram via HTTP
    token, _, ws_id = await _register(client, "race")
    diagram_id = await _create_diagram(client, token, ws_id, name="Race Diagram")

    # Look up the user_id from workspace members
    members_r = await client.get(
        f"/api/v1/workspaces/{ws_id}/members",
        headers=_auth(token),
    )
    assert members_r.status_code == 200, members_r.text
    user_id = uuid.UUID(members_r.json()[0]["user_id"])

    # Seed TWO undo entries: seq=1 (older) and seq=2 (newer/top).
    # Both browser tabs think seq=2 is the current top.
    # The entries must point at a real ModelObject so UndoTargetMissing is not
    # raised — otherwise the undo skip-hops logic would consume both entries in
    # the first request, leaving nothing for the second.
    from app.models.object import ModelObject, ObjectType

    async with async_session() as s:
        diag = (
            await s.execute(
                select(Diagram).where(Diagram.id == uuid.UUID(diagram_id))
            )
        ).scalar_one()

        # Create a real model object so the UPDATE undo can apply without
        # raising UndoTargetMissing (which would chain through both entries).
        real_obj = ModelObject(
            name="race-target",
            type=ObjectType.SYSTEM,
            workspace_id=diag.workspace_id,
        )
        s.add(real_obj)
        await s.flush()
        real_obj_id = real_obj.id

        common = dict(
            workspace_id=diag.workspace_id,
            user_id=user_id,
            diagram_id=uuid.UUID(diagram_id),
            draft_id=None,
            target_type=UndoTargetType.OBJECT,
            target_id=real_obj_id,
            action=UndoAction.UPDATE,
            inverse_payload={"before": {"name": "race-target"}},
            after_state={"name": "renamed"},
            state=UndoState.ACTIVE,
        )
        s.add(UndoEntry(**common, seq=1, forward_summary="first edit",
                        coalesce_key="obj:race-test:1"))
        s.add(UndoEntry(**common, seq=2, forward_summary="second edit",
                        coalesce_key="obj:race-test:2"))
        await s.commit()

    # Both requests carry expected_seq=2 (the stale cursor both tabs hold).
    # The first one arrives and succeeds (seq=2 matches the top → 200).
    # The second one arrives right after; the new top is seq=1 ≠ 2 → 409.
    res1, res2 = await asyncio.gather(
        client.post(
            f"/api/v1/diagrams/{diagram_id}/undo",
            headers=_auth(token),
            json={"expected_seq": 2},
        ),
        client.post(
            f"/api/v1/diagrams/{diagram_id}/undo",
            headers=_auth(token),
            json={"expected_seq": 2},
        ),
    )

    statuses = sorted([res1.status_code, res2.status_code])
    assert statuses == [200, 409], (
        f"Expected [200, 409], got {statuses}. "
        f"Bodies: {res1.text!r}, {res2.text!r}"
    )


# ─── Test 4 — Phase 2 stale-detection placeholder ───────────────────────────


@pytest.mark.skip(reason="Phase 2 — stale detection")
@pytest.mark.asyncio
async def test_alice_undo_skips_when_bob_overwrote_in_phase2():
    """When Phase 2 stale-detection lands, Alice's undo MUST detect that Bob's
    edit clobbered the field and skip rather than overwrite. Inverse of test 1."""
    pass
