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
