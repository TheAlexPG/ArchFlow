"""End-to-end versions + conflict detection."""
import uuid

from sqlalchemy import update


async def _register(client, tag: str = "v"):
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
    return r.json()[0]["id"]


async def _create_diagram_in_workspace(
    client, token: str, ws_id: str, name: str
) -> str:
    """Create a diagram AND backfill workspace_id on it (endpoint doesn't
    stamp workspace yet)."""
    r = await client.post(
        "/api/v1/diagrams",
        json={"name": name, "type": "system_landscape"},
        headers={"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id},
    )
    assert r.status_code == 201, r.text
    diagram_id = r.json()["id"]

    from app.core.database import async_session
    from app.models.diagram import Diagram

    async with async_session() as s:
        await s.execute(
            update(Diagram)
            .where(Diagram.id == uuid.UUID(diagram_id))
            .values(workspace_id=uuid.UUID(ws_id))
        )
        await s.commit()
    return diagram_id


async def _create_object(
    client, token: str, ws_id: str, name: str
) -> str:
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


async def test_apply_draft_creates_version_snapshot(client):
    token, _ = await _register(client, "vbase")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    await _create_object(client, token, ws_id, "System A")
    diagram_id = await _create_diagram_in_workspace(client, token, ws_id, "L1")

    # Fork into a draft
    r = await client.post(
        f"/api/v1/drafts/from-diagram/{diagram_id}",
        json={"name": "feature-x"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]

    # Forking creates a base_version snapshot — the list endpoint should
    # now show at least that one.
    r = await client.get("/api/v1/versions", headers=auth)
    assert r.status_code == 200
    before_count = len(r.json())
    assert before_count >= 1

    # Apply the draft — another snapshot rolls in with source=apply.
    r = await client.post(f"/api/v1/drafts/{draft_id}/apply", headers=auth)
    assert r.status_code == 200, r.text
    assert "version_id" in r.json(), r.json()
    apply_version_id = r.json()["version_id"]

    r = await client.get("/api/v1/versions", headers=auth)
    assert len(r.json()) == before_count + 1
    apply_row = next(v for v in r.json() if v["id"] == apply_version_id)
    assert apply_row["source"] == "apply"


async def test_conflict_detection_blocks_apply(client):
    """Classic conflict: fork an object, then edit the same object on main
    before applying. Apply should 409."""
    token, _ = await _register(client, "vconf")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    obj_id = await _create_object(client, token, ws_id, "System A")
    diagram_id = await _create_diagram_in_workspace(client, token, ws_id, "L1")

    # Place the object on the diagram so forking clones it.
    r = await client.post(
        f"/api/v1/diagrams/{diagram_id}/objects",
        json={"object_id": obj_id, "position_x": 0, "position_y": 0},
        headers=auth,
    )
    assert r.status_code == 201, r.text

    # Put a baseline snapshot in so the draft has a concrete base.
    r = await client.post("/api/v1/versions/snapshot", headers=auth)
    assert r.status_code == 201, r.text

    r = await client.post(
        f"/api/v1/drafts/from-diagram/{diagram_id}",
        json={"name": "rename-a"},
        headers=auth,
    )
    draft_id = r.json()["id"]

    # Find the forked clone of obj_id to edit it INSIDE the draft.
    from app.core.database import async_session
    from app.models.object import ModelObject
    from sqlalchemy import select

    async with async_session() as s:
        rows = list(
            (
                await s.execute(
                    select(ModelObject).where(
                        ModelObject.draft_id == uuid.UUID(draft_id)
                    )
                )
            ).scalars().all()
        )
        fork_obj_id = next(
            r.id for r in rows if r.source_object_id == uuid.UUID(obj_id)
        )

    # Draft edit: rename to "A-fork"
    r = await client.put(
        f"/api/v1/objects/{fork_obj_id}",
        json={"name": "A-fork"},
        headers=auth,
    )
    assert r.status_code == 200

    # Concurrent main edit: rename live obj to "A-main"
    r = await client.put(
        f"/api/v1/objects/{obj_id}",
        json={"name": "A-main"},
        headers=auth,
    )
    assert r.status_code == 200

    # Conflicts endpoint should list one
    r = await client.get(f"/api/v1/drafts/{draft_id}/conflicts", headers=auth)
    assert r.status_code == 200
    report = r.json()
    conflict_ids = {c["id"] for c in report["conflicts"]}
    assert obj_id in conflict_ids, report

    # Apply without force → 409
    r = await client.post(f"/api/v1/drafts/{draft_id}/apply", headers=auth)
    assert r.status_code == 409

    # Apply with force → success
    r = await client.post(
        f"/api/v1/drafts/{draft_id}/apply?force=true", headers=auth
    )
    assert r.status_code == 200, r.text


async def test_manual_snapshot_and_compare(client):
    token, _ = await _register(client, "vcmp")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    await _create_object(client, token, ws_id, "A")
    r1 = await client.post("/api/v1/versions/snapshot", headers=auth)
    assert r1.status_code == 201
    v1 = r1.json()["id"]

    await _create_object(client, token, ws_id, "B")
    r2 = await client.post("/api/v1/versions/snapshot", headers=auth)
    v2 = r2.json()["id"]

    r = await client.post(
        "/api/v1/versions/compare", json={"a": v1, "b": v2}, headers=auth
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["objects_added"] == 1
    assert body["summary"]["objects_removed"] == 0
    assert body["summary"]["objects_modified"] == 0
