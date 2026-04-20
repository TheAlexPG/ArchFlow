"""Notifications: mention extraction, creation, list, read, mark-all-read."""
import uuid


async def _register(client, name: str) -> tuple[str, str]:
    email = f"nt-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": "s3cret-pw!"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], email


def test_extract_mentions():
    from app.services.notification_service import extract_mentions

    assert extract_mentions("hey @alice and @bob") == sorted(["alice", "bob"]) or set(
        extract_mentions("hey @alice and @bob")
    ) == {"alice", "bob"}
    # Email-like @archflow.dev shouldn't be a mention (no leading whitespace).
    assert "archflow.dev" not in extract_mentions("email me at foo@archflow.dev")


async def test_mention_creates_notification_for_other_user(client):
    _, alice_email = await _register(client, "Alice")
    bob_token, bob_email = await _register(client, "Bob")

    # Alice posts a comment mentioning @Bob.
    # The mention pattern is on the name OR email local-part.
    bob_local = bob_email.split("@")[0]

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": alice_email, "password": "s3cret-pw!"},
    )
    alice_token = r.json()["access_token"]

    # We need any uuid as target_id; a random one is fine because the
    # comments endpoint only validates when target_type is known.
    target_id = str(uuid.uuid4())
    r = await client.post(
        "/api/v1/comments",
        json={
            "target_type": "diagram",
            "target_id": target_id,
            "body": f"Hey @{bob_local}, can you review?",
        },
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 201, r.text

    # Bob should see one unread notification.
    r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert any(n["kind"] == "mention" for n in rows)
    notif_id = next(n["id"] for n in rows if n["kind"] == "mention")

    # Mark read.
    r = await client.post(
        f"/api/v1/notifications/{notif_id}/read",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 204

    # Unread count drops.
    r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    before = 1  # we only seeded one mention
    assert r.json()["count"] == max(0, before - 1)


async def test_no_self_notify(client):
    """Mentioning yourself in a comment shouldn't create a notification."""
    token, email = await _register(client, "Solo")
    local = email.split("@")[0]

    r = await client.post(
        "/api/v1/comments",
        json={
            "target_type": "diagram",
            "target_id": str(uuid.uuid4()),
            "body": f"note to self: @{local}",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201

    r = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    mentions = [n for n in r.json() if n["kind"] == "mention"]
    assert mentions == []


async def test_mark_all_read(client):
    _, alice_email = await _register(client, "Alice2")
    bob_token, bob_email = await _register(client, "Bob2")
    bob_local = bob_email.split("@")[0]

    alice_token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": alice_email, "password": "s3cret-pw!"},
        )
    ).json()["access_token"]

    for _ in range(3):
        await client.post(
            "/api/v1/comments",
            json={
                "target_type": "diagram",
                "target_id": str(uuid.uuid4()),
                "body": f"@{bob_local} ping",
            },
            headers={"Authorization": f"Bearer {alice_token}"},
        )

    r = await client.post(
        "/api/v1/notifications/read-all",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] >= 3

    r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.json()["count"] == 0
