import uuid


async def test_get_me_returns_profile(client):
    email = f"me-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Test User", "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]

    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == email
    assert data["name"] == "Test User"
    assert "id" in data


async def test_patch_me_updates_undo_settings(client):
    """PATCH /api/v1/auth/me writes `undo_settings` and GET /me round-trips it."""
    email = f"metest-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Me Tester", "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]

    r = await client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"undo_settings": {"include_comments_in_undo": True}},
    )
    assert r.status_code == 200
    assert r.json()["undo_settings"] == {"include_comments_in_undo": True}

    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["undo_settings"] == {"include_comments_in_undo": True}
