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


async def test_invite_existing_user_is_pending_until_accepted(client):
    owner_token, _, ws_id = await _register(client, "owner")
    alice_token, alice_email, _ = await _register(client, "alice")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "invite_created"
    invite_id = r.json()["invite"]["id"]

    # Alice isn't a member yet.
    members = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).json()
    assert alice_email not in {m["email"] for m in members}

    # She sees the pending invite on her side.
    r = await client.get(
        "/api/v1/me/invites",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200
    assert any(i["id"] == invite_id for i in r.json())

    # Accept → now she's a member.
    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200

    members = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/members",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    ).json()
    assert alice_email in {m["email"] for m in members}


async def test_non_admin_cant_invite(client):
    owner_token, _, ws_id = await _register(client, "owner")
    alice_token, alice_email, _ = await _register(client, "alice")

    # Invite Alice as viewer, then have her accept, then Alice tries to
    # invite someone → 403.
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "viewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    invite_id = r.json()["invite"]["id"]
    await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {alice_token}"},
    )

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


async def test_google_oauth_disabled_without_creds(client):
    """With no GOOGLE_CLIENT_ID in settings, both endpoints should 503 so the
    SPA falls back to email/password without exposing half-configured OAuth."""
    r = await client.get("/api/v1/auth/oauth/google/login")
    assert r.status_code == 503

    r = await client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "any"},
    )
    assert r.status_code == 503


async def test_google_oauth_login_redirects_when_configured(client, monkeypatch):
    """When creds are present, /login must 302 to accounts.google.com with the
    configured client_id + redirect_uri."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    monkeypatch.setattr(
        settings,
        "google_redirect_uri",
        "http://localhost:8000/api/v1/auth/oauth/google/callback",
    )

    r = await client.get(
        "/api/v1/auth/oauth/google/login", follow_redirects=False
    )
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert "accounts.google.com" in loc
    assert "client_id=test-client-id" in loc
    assert "scope=openid" in loc
