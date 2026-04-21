"""End-to-end: admin creates team, adds member, grants per-diagram access,
then a non-admin user sees only the diagrams their team is granted."""
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


async def _create_diagram(client, token: str, ws_id: str, name: str) -> str:
    r = await client.post(
        "/api/v1/diagrams",
        json={"name": name, "type": "system_landscape"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-ID": ws_id,
        },
    )
    assert r.status_code == 201, r.text
    diagram = r.json()
    # The create endpoint doesn't yet stamp workspace_id automatically — run
    # a direct DB update so our access filtering actually has something to
    # filter on.
    from app.core.database import async_session
    from app.models.diagram import Diagram
    from sqlalchemy import update

    async with async_session() as s:
        await s.execute(
            update(Diagram)
            .where(Diagram.id == uuid.UUID(diagram["id"]))
            .values(workspace_id=uuid.UUID(ws_id))
        )
        await s.commit()
    return diagram["id"]


async def test_team_acl_restricts_diagram_visibility(client):
    owner_token, _ = await _register(client, "owner")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    c1_id = await _create_diagram(client, owner_token, ws_id, "C1 landscape")
    c2_restricted_id = await _create_diagram(
        client, owner_token, ws_id, "C2 payments (restricted)"
    )
    c3_restricted_id = await _create_diagram(
        client, owner_token, ws_id, "C3 checkout (restricted)"
    )

    # Create frontend team
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "Frontend"},
        headers=owner_auth,
    )
    assert r.status_code == 201, r.text
    frontend_team_id = r.json()["id"]

    # Invite Alice (frontend dev) as editor
    alice_token, alice_email = await _register(client, "alice")
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers=owner_auth,
    )
    assert r.status_code == 201
    invite_id = r.json()["invite"]["id"]

    # Alice must accept before she's a member.
    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200

    # Alice's user_id
    members = (
        await client.get(f"/api/v1/workspaces/{ws_id}/members", headers=owner_auth)
    ).json()
    alice_id = next(m["user_id"] for m in members if m["email"] == alice_email)

    # Add Alice to frontend team
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams/{frontend_team_id}/members",
        json={"user_id": alice_id},
        headers=owner_auth,
    )
    assert r.status_code == 201

    # Create a backend team so C3 can be restricted to it (Alice isn't in it).
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "Backend"},
        headers=owner_auth,
    )
    backend_team_id = r.json()["id"]

    # Grant frontend team read on C2; grant backend team read on C3. That
    # makes C3 "restricted but not to Alice", so she shouldn't see it.
    for diag_id, team_id in (
        (c2_restricted_id, frontend_team_id),
        (c3_restricted_id, backend_team_id),
    ):
        r = await client.post(
            f"/api/v1/diagrams/{diag_id}/access/teams",
            json={"team_id": team_id, "level": "read"},
            headers=owner_auth,
        )
        assert r.status_code == 201

    # Log Alice in
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": alice_email, "password": "s3cret-pw!"},
    )
    alice_token = r.json()["access_token"]
    alice_auth = {"Authorization": f"Bearer {alice_token}", "X-Workspace-ID": ws_id}

    # Alice lists diagrams — should see C1 (open) and C2 (granted) but NOT C3.
    r = await client.get("/api/v1/diagrams", headers=alice_auth)
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert c1_id in ids
    assert c2_restricted_id in ids
    assert c3_restricted_id not in ids

    # Direct fetch on C3 is a 403 for Alice
    r = await client.get(f"/api/v1/diagrams/{c3_restricted_id}", headers=alice_auth)
    assert r.status_code == 403

    # Owner (admin) can still see all of them
    r = await client.get("/api/v1/diagrams", headers=owner_auth)
    owner_ids = {d["id"] for d in r.json()}
    assert {c1_id, c2_restricted_id, c3_restricted_id}.issubset(owner_ids)


async def test_direct_user_grant(client):
    """Admin grants Alice personally to a restricted diagram — she sees it
    even though she's in no granted team."""
    owner_token, _ = await _register(client, "ownerU")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    # Create restricted diagram (give it a throwaway team grant so it's
    # restricted, but one Alice is NOT in).
    restricted_id = await _create_diagram(client, owner_token, ws_id, "Strategy")
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "Leadership"},
        headers=owner_auth,
    )
    leadership_team_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/diagrams/{restricted_id}/access/teams",
        json={"team_id": leadership_team_id, "level": "read"},
        headers=owner_auth,
    )
    assert r.status_code == 201

    # Invite Alice as editor (no team pre-assignment)
    alice_token, alice_email = await _register(client, "aliceU")
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": alice_email, "role": "editor"},
        headers=owner_auth,
    )
    invite_id = r.json()["invite"]["id"]

    # Alice accepts.
    await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {alice_token}"},
    )

    members = (
        await client.get(f"/api/v1/workspaces/{ws_id}/members", headers=owner_auth)
    ).json()
    alice_id = next(m["user_id"] for m in members if m["email"] == alice_email)

    # Log Alice in — she shouldn't see the restricted diagram yet
    alice_token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": alice_email, "password": "s3cret-pw!"},
        )
    ).json()["access_token"]
    alice_auth = {"Authorization": f"Bearer {alice_token}", "X-Workspace-ID": ws_id}

    r = await client.get(f"/api/v1/diagrams/{restricted_id}", headers=alice_auth)
    assert r.status_code == 403

    # Owner grants Alice directly
    r = await client.post(
        f"/api/v1/diagrams/{restricted_id}/access/users",
        json={"user_id": alice_id, "level": "read"},
        headers=owner_auth,
    )
    assert r.status_code == 201

    # Now she can see it
    r = await client.get(f"/api/v1/diagrams/{restricted_id}", headers=alice_auth)
    assert r.status_code == 200

    # And the list endpoint surfaces it
    r = await client.get("/api/v1/diagrams", headers=alice_auth)
    assert restricted_id in {d["id"] for d in r.json()}

    # Revoke the direct grant → she loses access again
    r = await client.delete(
        f"/api/v1/diagrams/{restricted_id}/access/users/{alice_id}",
        headers=owner_auth,
    )
    assert r.status_code == 204

    r = await client.get(f"/api/v1/diagrams/{restricted_id}", headers=alice_auth)
    assert r.status_code == 403


async def test_invite_pre_assigns_teams(client):
    """Admin picks teams in the invite form; after Bob accepts via the
    in-app flow he lands in those teams automatically."""
    owner_token, _ = await _register(client, "ownerT")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    # Two teams ahead of time
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "Frontend"},
        headers=owner_auth,
    )
    frontend_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "QA"},
        headers=owner_auth,
    )
    qa_id = r.json()["id"]

    # Bob already has an account before the invite goes out.
    bob_token, bob_email = await _register(client, "bobT")

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={
            "email": bob_email,
            "role": "editor",
            "team_ids": [frontend_id, qa_id],
        },
        headers=owner_auth,
    )
    assert r.status_code == 201
    assert r.json()["type"] == "invite_created"
    invite_id = r.json()["invite"]["id"]

    # Bob sees the pending invite and accepts it in-app.
    r = await client.get(
        "/api/v1/me/invites",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200
    assert any(i["id"] == invite_id for i in r.json())

    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200

    # Both teams now list Bob.
    for tid in (frontend_id, qa_id):
        members = (
            await client.get(
                f"/api/v1/workspaces/{ws_id}/teams/{tid}/members",
                headers=owner_auth,
            )
        ).json()
        emails = {m["email"] for m in members}
        assert bob_email in emails, f"Bob missing from team {tid}"


async def test_invite_pre_assigned_teams_applied_on_accept(client):
    """Invite generated for an email that doesn't have an account yet —
    teams get applied only after the invitee registers and accepts."""
    owner_token, _ = await _register(client, "ownerA")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/teams",
        json={"name": "Platform"},
        headers=owner_auth,
    )
    platform_id = r.json()["id"]

    import uuid

    new_email = f"new-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": new_email, "role": "editor", "team_ids": [platform_id]},
        headers=owner_auth,
    )
    assert r.status_code == 201
    assert r.json()["type"] == "invite_created"
    token = r.json()["invite"]["token"]
    assert r.json()["invite"]["team_ids"] == [platform_id]

    # The invitee signs up
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": new_email, "name": "New Dev", "password": "s3cret-pw!"},
    )
    invitee_token = r.json()["access_token"]

    # They accept the invite
    r = await client.post(
        "/api/v1/invites/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert r.status_code == 200

    # Platform team has them now
    members = (
        await client.get(
            f"/api/v1/workspaces/{ws_id}/teams/{platform_id}/members",
            headers=owner_auth,
        )
    ).json()
    assert any(m["email"] == new_email for m in members)
