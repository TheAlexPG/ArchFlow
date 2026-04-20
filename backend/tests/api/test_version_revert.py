"""Revert round-trip: v1 (A), v2 (A+B), revert to v1 (B gone), revert again
to v2 (B back)."""
import uuid

from sqlalchemy import update


async def _register(client, tag: str = "rv"):
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": tag.title(), "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()[0]["id"]


async def _create_object(client, token: str, ws_id: str, name: str) -> str:
    r = await client.post(
        "/api/v1/objects",
        json={"name": name, "type": "system"},
        headers={"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id},
    )
    assert r.status_code == 201, r.text
    obj_id = r.json()["id"]
    from app.core.database import async_session
    from app.models.object import ModelObject

    async with async_session() as s:
        await s.execute(
            update(ModelObject)
            .where(ModelObject.id == uuid.UUID(obj_id))
            .values(workspace_id=uuid.UUID(ws_id))
        )
        await s.commit()
    return obj_id


async def _list_object_names(client, token: str, ws_id: str) -> set[str]:
    """Live object names in this specific workspace (GET /objects isn't
    workspace-filtered yet, so query the DB directly)."""
    from app.core.database import async_session
    from app.models.object import ModelObject
    from sqlalchemy import select

    async with async_session() as s:
        rows = list(
            (
                await s.execute(
                    select(ModelObject).where(
                        ModelObject.workspace_id == uuid.UUID(ws_id),
                        ModelObject.draft_id.is_(None),
                    )
                )
            ).scalars().all()
        )
    return {r.name for r in rows}


async def test_revert_round_trip(client):
    token = await _register(client)
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    await _create_object(client, token, ws_id, "A")
    r = await client.post("/api/v1/versions/snapshot", headers=auth)
    v1 = r.json()["id"]

    await _create_object(client, token, ws_id, "B")
    r = await client.post("/api/v1/versions/snapshot", headers=auth)
    v2 = r.json()["id"]

    # Sanity: both objects live right now.
    names = await _list_object_names(client, token, ws_id)
    assert {"A", "B"}.issubset(names)

    # Revert to v1 (only A).
    r = await client.post(f"/api/v1/versions/{v1}/revert", headers=auth)
    assert r.status_code == 201, r.text
    revert_row = r.json()
    assert revert_row["source"] == "revert"

    names = await _list_object_names(client, token, ws_id)
    assert "A" in names
    assert "B" not in names

    # Revert forward to v2 — B should be back.
    r = await client.post(f"/api/v1/versions/{v2}/revert", headers=auth)
    assert r.status_code == 201

    names = await _list_object_names(client, token, ws_id)
    assert {"A", "B"}.issubset(names)

    # History is preserved: v1, v2, revert→v1, revert→v2 → 4 rows at least.
    r = await client.get("/api/v1/versions", headers=auth)
    labels = [v["source"] for v in r.json()]
    assert labels.count("revert") >= 2
    assert labels.count("manual") >= 2


async def test_revert_edits_existing_object(client):
    """Revert should restore renamed object back to its old name, not
    delete-and-recreate."""
    token = await _register(client, "rvren")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    obj_id = await _create_object(client, token, ws_id, "Original")
    r = await client.post("/api/v1/versions/snapshot", headers=auth)
    v1 = r.json()["id"]

    r = await client.put(
        f"/api/v1/objects/{obj_id}",
        json={"name": "Renamed"},
        headers=auth,
    )
    assert r.status_code == 200

    r = await client.post(f"/api/v1/versions/{v1}/revert", headers=auth)
    assert r.status_code == 201

    r = await client.get(f"/api/v1/objects/{obj_id}", headers=auth)
    assert r.status_code == 200
    assert r.json()["name"] == "Original"
