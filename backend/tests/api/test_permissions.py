import uuid


async def _register(client, tag: str = "p") -> tuple[str, str, str]:
    """Register a user and return (token, user_id, workspace_id)."""
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": f"{tag.title()} Tester", "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    ws = (
        await client.get(
            "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
        )
    ).json()[0]
    return token, email, ws["id"]


async def test_invite_existing_user_adds_membership(client):
    owner_token, _, ws_id = await _register(client, "owner")
    _, alice_email, _ = await _register(client, "alice")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "member_added"

    members = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).json()
    emails = {m["email"] for m in members}
    assert alice_email in emails


async def test_non_admin_cant_invite(client):
    owner_token, _, ws_id = await _register(client, "owner")
    _, alice_email, _ = await _register(client, "alice")

    # Add Alice as viewer, then Alice tries to invite someone → 403.
    await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "viewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    # Alice signs in implicitly via her own token — first get it:
    r_login = await client.post(
        "/api/v1/auth/login",
        json={"email": alice_email, "password": "s3cret-pw!"},
    )
    alice_token = r_login.json()["access_token"]

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": "random@example.com", "role": "viewer"},
        headers={
            "Authorization": f"Bearer {alice_token}",
            "X-Workspace-ID": ws_id,
        },
    )
    assert r.status_code == 403


async def test_cannot_demote_last_owner(client):
    owner_token, _, ws_id = await _register(client, "owner")

    # Find the owner's user id
    me = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).json()
    owner_user_id = me[0]["user_id"]

    r = await client.patch(
        f"/api/v1/workspaces/{ws_id}/members/{owner_user_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 400
    assert "last owner" in r.json()["detail"].lower()


async def test_oauth_stub_flow(client):
    r = await client.get("/api/v1/auth/oauth/google/login")
    assert r.status_code == 200
    body = r.json()
    assert body["stub"] is True
    assert "callback" in body["authorize_url"]

    r = await client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": f"oauth-{uuid.uuid4().hex[:6]}@example.com"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stub"] is True
    assert body["is_new_user"] is True
    assert body["access_token"]
