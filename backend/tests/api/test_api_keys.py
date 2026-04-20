import uuid


async def _register(client) -> str:
    email = f"apikey-{uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "APIKey Tester", "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_api_key_end_to_end(client):
    """Create → list → use as Bearer → reject forged → revoke → reject revoked.

    Kept as one test to share the event loop / asyncpg engine (pytest-asyncio
    in auto mode creates a fresh loop per test, which the shared engine can't
    survive across).
    """
    token = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    # Create
    r = await client.post(
        "/api/v1/api-keys",
        json={"name": "ci-bot", "permissions": ["read", "write"]},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "ci-bot"
    assert body["permissions"] == ["read", "write"]
    assert body["secret"].startswith("ak_")
    assert body["key_prefix"] == body["secret"][:12]
    key_id = body["id"]
    secret = body["secret"]

    # List — secret never returned again
    r = await client.get("/api/v1/api-keys", headers=auth)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert listed[0]["id"] == key_id

    # Authenticate with the key itself
    r = await client.get(
        "/api/v1/api-keys", headers={"Authorization": f"Bearer {secret}"}
    )
    assert r.status_code == 200

    # Forged secret — right prefix, wrong tail
    forged = body["key_prefix"] + "X" * 40
    r = await client.get(
        "/api/v1/api-keys", headers={"Authorization": f"Bearer {forged}"}
    )
    assert r.status_code == 401

    # Non-ak_ garbage falls through to JWT path → 401
    r = await client.get(
        "/api/v1/api-keys", headers={"Authorization": "Bearer not-a-key"}
    )
    assert r.status_code == 401

    # Revoke
    r = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth)
    assert r.status_code == 204

    # Revoked key no longer authenticates
    r = await client.get(
        "/api/v1/api-keys", headers={"Authorization": f"Bearer {secret}"}
    )
    assert r.status_code == 401
