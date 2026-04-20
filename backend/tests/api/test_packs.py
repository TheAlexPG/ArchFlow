"""Tests for diagram pack CRUD and diagram pack assignment."""
import uuid


async def _register(client, tag: str = "p"):
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": tag.title(), "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], email


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


async def _create_diagram(client, token: str, ws_id: str, name: str = "Test diagram") -> str:
    r = await client.post(
        "/api/v1/diagrams",
        json={"name": name, "type": "system_landscape"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-ID": ws_id,
        },
    )
    assert r.status_code == 201, r.text
    diagram = r.json()
    # Stamp workspace_id directly so pack assignment can validate workspace match.
    from app.core.database import async_session
    from app.models.diagram import Diagram
    from sqlalchemy import update

    async with async_session() as s:
        await s.execute(
            update(Diagram)
            .where(Diagram.id == uuid.UUID(diagram["id"]))
            .values(workspace_id=uuid.UUID(ws_id))
        )
        await s.commit()
    return diagram["id"]


async def _invite_as_editor(client, owner_auth: dict, ws_id: str, email: str) -> str:
    """Invite an existing user as editor; return their login token."""
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": email, "role": "editor"},
        headers=owner_auth,
    )
    assert r.status_code == 201, r.text
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-pw!"},
    )
    return r2.json()["access_token"]


# ─── Pack CRUD ────────────────────────────────────────────────

async def test_create_list_pack(client):
    token, _ = await _register(client, "packA")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Q2 planning"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    pack = r.json()
    assert pack["name"] == "Q2 planning"
    assert pack["workspace_id"] == ws_id

    r2 = await client.get(f"/api/v1/workspaces/{ws_id}/packs", headers=auth)
    assert r2.status_code == 200
    names = [p["name"] for p in r2.json()]
    assert "Q2 planning" in names


async def test_rename_pack(client):
    token, _ = await _register(client, "packB")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Old name"},
        headers=auth,
    )
    pack_id = r.json()["id"]

    r2 = await client.patch(
        f"/api/v1/workspaces/{ws_id}/packs/{pack_id}",
        json={"name": "New name"},
        headers=auth,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "New name"


async def test_delete_pack(client):
    token, _ = await _register(client, "packC")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "To delete"},
        headers=auth,
    )
    pack_id = r.json()["id"]

    r2 = await client.delete(f"/api/v1/workspaces/{ws_id}/packs/{pack_id}", headers=auth)
    assert r2.status_code == 204

    r3 = await client.get(f"/api/v1/workspaces/{ws_id}/packs", headers=auth)
    ids = [p["id"] for p in r3.json()]
    assert pack_id not in ids


async def test_non_admin_cannot_create_pack(client):
    owner_token, _ = await _register(client, "packD-owner")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    _, editor_email = await _register(client, "packD-editor")
    editor_token = await _invite_as_editor(client, owner_auth, ws_id, editor_email)
    editor_auth = {"Authorization": f"Bearer {editor_token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Forbidden"},
        headers=editor_auth,
    )
    assert r.status_code == 403, r.text


# ─── Diagram pack assignment ───────────────────────────────────

async def test_diagram_surfaces_pack_id(client):
    token, _ = await _register(client, "packE")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    pack_r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Domain X"},
        headers=auth,
    )
    pack_id = pack_r.json()["id"]

    diagram_id = await _create_diagram(client, token, ws_id)

    # Assign the diagram to the pack
    r = await client.put(
        f"/api/v1/diagrams/{diagram_id}/pack",
        json={"pack_id": pack_id},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pack_id"] == pack_id

    # List diagrams — the pack_id should be present
    r2 = await client.get("/api/v1/diagrams", headers=auth)
    diagrams = {d["id"]: d for d in r2.json()}
    assert diagrams[diagram_id]["pack_id"] == pack_id


async def test_remove_diagram_from_pack(client):
    token, _ = await _register(client, "packF")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    pack_r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Temp pack"},
        headers=auth,
    )
    pack_id = pack_r.json()["id"]

    diagram_id = await _create_diagram(client, token, ws_id)

    # Assign
    await client.put(
        f"/api/v1/diagrams/{diagram_id}/pack",
        json={"pack_id": pack_id},
        headers=auth,
    )

    # Remove (null out)
    r = await client.put(
        f"/api/v1/diagrams/{diagram_id}/pack",
        json={"pack_id": None},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pack_id"] is None


async def test_delete_pack_nullifies_diagram_pack_id(client):
    """When a pack is deleted, diagrams that belonged to it become unfiled."""
    token, _ = await _register(client, "packG")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    pack_r = await client.post(
        f"/api/v1/workspaces/{ws_id}/packs",
        json={"name": "Legacy"},
        headers=auth,
    )
    pack_id = pack_r.json()["id"]

    diagram_id = await _create_diagram(client, token, ws_id)

    await client.put(
        f"/api/v1/diagrams/{diagram_id}/pack",
        json={"pack_id": pack_id},
        headers=auth,
    )

    # Delete the pack
    await client.delete(f"/api/v1/workspaces/{ws_id}/packs/{pack_id}", headers=auth)

    # Diagram pack_id should be NULL now
    r = await client.get(f"/api/v1/diagrams/{diagram_id}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["pack_id"] is None


async def test_cannot_move_diagram_to_pack_in_different_workspace(client):
    """400 when trying to assign a diagram to a pack from another workspace."""
    owner_a_token, _ = await _register(client, "packH-a")
    ws_a = await _workspace_id(client, owner_a_token)
    auth_a = {"Authorization": f"Bearer {owner_a_token}", "X-Workspace-ID": ws_a}

    owner_b_token, _ = await _register(client, "packH-b")
    ws_b = await _workspace_id(client, owner_b_token)
    auth_b = {"Authorization": f"Bearer {owner_b_token}", "X-Workspace-ID": ws_b}

    # Create a pack in workspace B
    pack_r = await client.post(
        f"/api/v1/workspaces/{ws_b}/packs",
        json={"name": "B pack"},
        headers=auth_b,
    )
    pack_b_id = pack_r.json()["id"]

    # Create a diagram in workspace A
    diagram_id = await _create_diagram(client, owner_a_token, ws_a)

    # Try to assign workspace-A diagram to workspace-B pack
    r = await client.put(
        f"/api/v1/diagrams/{diagram_id}/pack",
        json={"pack_id": pack_b_id},
        headers=auth_a,
    )
    assert r.status_code == 400, r.text
