import uuid


async def _register(client) -> str:
    email = f"wh-{uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "WH Tester", "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def test_webhook_crud_and_events_list(client):
    token = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    # Event catalogue is exposed
    r = await client.get("/api/v1/webhooks/events", headers=auth)
    assert r.status_code == 200
    events = r.json()
    assert "object.created" in events
    assert "draft.applied" in events

    # Create webhook
    r = await client.post(
        "/api/v1/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["object.created", "diagram.deleted"],
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["events"] == ["object.created", "diagram.deleted"]
    assert body["enabled"] is True
    assert len(body["secret"]) > 20
    webhook_id = body["id"]

    # List
    r = await client.get("/api/v1/webhooks", headers=auth)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert "secret" not in rows[0]

    # Reject unknown event
    r = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/x", "events": ["nope.bad"]},
        headers=auth,
    )
    assert r.status_code == 400

    # Test ping queued
    r = await client.post(f"/api/v1/webhooks/{webhook_id}/test", headers=auth)
    assert r.status_code == 202
    assert r.json() == {"queued": True}

    # Delete
    r = await client.delete(f"/api/v1/webhooks/{webhook_id}", headers=auth)
    assert r.status_code == 204

    r = await client.get("/api/v1/webhooks", headers=auth)
    assert r.json() == []
