"""Pending-approval invite flow: list, accept, decline, revoke."""
import uuid


async def _register(client, tag: str = "t"):
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


async def test_invite_existing_user_shows_up_in_my_invites(client):
    owner_token, _ = await _register(client, "ownerMI")
    ws_id = await _workspace_id(client, owner_token)
    alice_token, alice_email = await _register(client, "aliceMI")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201
    assert r.json()["type"] == "invite_created"

    r = await client.get(
        "/api/v1/me/invites",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200
    invites = r.json()
    assert len(invites) == 1
    assert invites[0]["workspace_id"] == ws_id
    assert invites[0]["role"] == "editor"


async def test_decline_invite_removes_it(client):
    owner_token, _ = await _register(client, "ownerD")
    ws_id = await _workspace_id(client, owner_token)
    alice_token, alice_email = await _register(client, "aliceD")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    invite_id = r.json()["invite"]["id"]

    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/decline",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 204

    r = await client.get(
        "/api/v1/me/invites",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.json() == []

    # Not a member either.
    members = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).json()
    assert alice_email not in {m["email"] for m in members}


async def test_revoke_pending_invite(client):
    owner_token, _ = await _register(client, "ownerR")
    ws_id = await _workspace_id(client, owner_token)
    alice_token, alice_email = await _register(client, "aliceR")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    invite_id = r.json()["invite"]["id"]

    r = await client.delete(
        f"/api/v1/workspaces/{ws_id}/invites/{invite_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 204

    # Alice no longer sees it, and accepting returns an error.
    r = await client.get(
        "/api/v1/me/invites",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.json() == []

    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 400


async def test_cannot_accept_someone_elses_invite(client):
    owner_token, _ = await _register(client, "ownerX")
    ws_id = await _workspace_id(client, owner_token)
    _, alice_email = await _register(client, "aliceX")
    mallory_token, _ = await _register(client, "malloryX")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    invite_id = r.json()["invite"]["id"]

    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {mallory_token}"},
    )
    assert r.status_code == 400


async def test_duplicate_pending_invite_blocked(client):
    owner_token, _ = await _register(client, "ownerDup")
    ws_id = await _workspace_id(client, owner_token)
    _, bob_email = await _register(client, "bobDup")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": bob_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201

    # Second invite should fail while the first is still pending.
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": bob_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 400
