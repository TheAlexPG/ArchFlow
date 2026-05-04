"""Integration tests for undo/redo/history REST endpoints.

Auth pattern: local `_register` helper (same as test_permissions.py) —
registers a user, returns (token, email, workspace_id).  Diagrams are created
via POST /api/v1/diagrams (HTTP layer) so they live in the same DB session
scope as the client requests.

Session fixture note: the `client` fixture uses the session-scoped event loop
(see conftest.py), so all tests here share one loop but each registers fresh
users to avoid state leaks.
"""
import uuid

import pytest

from app.core.database import async_session


# ─── Helpers ────────────────────────────────────────────────────────────────


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


async def _create_diagram(client, token: str, ws_id: str, name: str = "Test Diag") -> str:
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


# ─── Tests ───────────────────────────────────────────────────────────────────


async def test_undo_returns_204_on_empty_stack(client):
    """Empty undo stack → 204 No Content."""
    token, _, ws_id = await _register(client, "undo204")
    diagram_id = await _create_diagram(client, token, ws_id)

    res = await client.post(
        f"/api/v1/diagrams/{diagram_id}/undo",
        headers=_auth(token),
        json={},
    )
    assert res.status_code == 204, res.text


async def test_redo_returns_204_on_empty_stack(client):
    """Empty redo stack → 204 No Content."""
    token, _, ws_id = await _register(client, "redo204")
    diagram_id = await _create_diagram(client, token, ws_id)

    res = await client.post(
        f"/api/v1/diagrams/{diagram_id}/redo",
        headers=_auth(token),
        json={},
    )
    assert res.status_code == 204, res.text


async def test_undo_history_empty_returns_empty_list(client):
    """GET /history on fresh diagram → empty entries list, null cursor_seq."""
    token, _, ws_id = await _register(client, "hist")
    diagram_id = await _create_diagram(client, token, ws_id)

    res = await client.get(
        f"/api/v1/diagrams/{diagram_id}/history",
        headers=_auth(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entries"] == []
    assert body["cursor_seq"] is None


async def test_undo_to_404_for_missing_entry(client):
    """POST /undo-to/<random-uuid> → 404 with correct error code."""
    token, _, ws_id = await _register(client, "undoto")
    diagram_id = await _create_diagram(client, token, ws_id)
    random_entry_id = str(uuid.uuid4())

    res = await client.post(
        f"/api/v1/diagrams/{diagram_id}/undo-to/{random_entry_id}",
        headers=_auth(token),
        json={},
    )
    assert res.status_code == 404, res.text
    assert res.json()["detail"]["code"] == "undo_entry_not_found"


async def test_unauthenticated_returns_401(client):
    """No Authorization header → 401 on all four endpoints."""
    fake_id = str(uuid.uuid4())

    for method, path in [
        ("post", f"/api/v1/diagrams/{fake_id}/undo"),
        ("post", f"/api/v1/diagrams/{fake_id}/redo"),
        ("get",  f"/api/v1/diagrams/{fake_id}/history"),
        ("post", f"/api/v1/diagrams/{fake_id}/undo-to/{fake_id}"),
    ]:
        kw = {} if method == "get" else {"json": {}}
        res = await getattr(client, method)(path, **kw)
        assert res.status_code == 401, f"{method.upper()} {path} returned {res.status_code}"


async def test_non_member_returns_403(client):
    """A user who is not in the workspace gets 403 on undo."""
    owner_token, _, ws_id = await _register(client, "owner403")
    stranger_token, _, _ = await _register(client, "stranger403")
    diagram_id = await _create_diagram(client, owner_token, ws_id)

    res = await client.post(
        f"/api/v1/diagrams/{diagram_id}/undo",
        headers=_auth(stranger_token),
        json={},
    )
    assert res.status_code == 403, res.text


async def test_undo_seq_mismatch_returns_409(client):
    """Sending a wrong expected_seq → 409 with undo_seq_mismatch."""
    token, _, ws_id = await _register(client, "seq409")
    diagram_id = await _create_diagram(client, token, ws_id)

    # Seed one undo entry directly via the service so there's something on
    # the stack, then hit the endpoint with the wrong expected_seq.
    from app.models.undo_entry import UndoAction, UndoState, UndoTargetType
    from app.models.workspace import Workspace
    from sqlalchemy import select

    async with async_session() as s:
        # Look up workspace_id
        from app.models.workspace import WorkspaceMember
        from app.models.user import User
        from app.models.diagram import Diagram

        # Fetch the diagram to get its workspace_id
        diag = (
            await s.execute(
                select(Diagram).where(Diagram.id == uuid.UUID(diagram_id))
            )
        ).scalar_one()
        # Fetch user_id for the token-holder via workspace members.
        members_r = await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers=_auth(token),
        )
        assert members_r.status_code == 200, members_r.text
        members = members_r.json()
        user_id = uuid.UUID(members[0]["user_id"])

        from app.models.undo_entry import UndoEntry
        entry = UndoEntry(
            workspace_id=diag.workspace_id,
            user_id=user_id,
            diagram_id=uuid.UUID(diagram_id),
            draft_id=None,
            seq=1,
            target_type=UndoTargetType.OBJECT,
            target_id=uuid.uuid4(),
            action=UndoAction.UPDATE,
            forward_summary="test edit",
            inverse_payload={"before": {"name": "old"}},
            after_state={"name": "new"},
            coalesce_key="obj:test",
            state=UndoState.ACTIVE,
        )
        s.add(entry)
        await s.commit()

    # Now POST /undo with a deliberately wrong expected_seq
    res = await client.post(
        f"/api/v1/diagrams/{diagram_id}/undo",
        headers=_auth(token),
        json={"expected_seq": 999},
    )
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "undo_seq_mismatch"
    assert detail["actual_seq"] == 1
