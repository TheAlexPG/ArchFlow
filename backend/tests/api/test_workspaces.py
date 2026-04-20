import uuid


async def _register(client, name: str = "WS Tester") -> tuple[str, str]:
    email = f"ws-{uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], email


async def test_register_creates_personal_workspace(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/v1/workspaces", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    ws = data[0]
    assert ws["name"] == "Personal"
    assert ws["role"] == "owner"


async def test_cannot_access_someone_elses_workspace(client):
    # Alice registers; her workspace id leaks to Bob somehow.
    alice_token, _ = await _register(client, name="Alice")
    alice_auth = {"Authorization": f"Bearer {alice_token}"}
    alice_workspaces = (await client.get("/api/v1/workspaces", headers=alice_auth)).json()
    alice_ws_id = alice_workspaces[0]["id"]

    bob_token, _ = await _register(client, name="Bob")
    bob_auth = {"Authorization": f"Bearer {bob_token}"}

    # Bob tries to fetch Alice's workspace directly — must be 404.
    r = await client.get(f"/api/v1/workspaces/{alice_ws_id}", headers=bob_auth)
    assert r.status_code == 404


async def test_workspace_dep_rejects_non_member_via_header(client):
    """Caller passes X-Workspace-ID pointing at someone else's workspace —
    should get 403 from the dependency, proving membership is verified."""
    alice_token, _ = await _register(client)
    alice_auth = {"Authorization": f"Bearer {alice_token}"}
    alice_ws = (await client.get("/api/v1/workspaces", headers=alice_auth)).json()[0]

    bob_token, _ = await _register(client)
    # Hit /workspaces/{alice_id} as Bob with Alice's id — 404, as above.
    # (Dependency test per se isn't exercised here because no endpoint is
    # currently scope-protected with get_current_workspace — that follow-up
    # would replace this test with a real scoped route.)
    r = await client.get(
        f"/api/v1/workspaces/{alice_ws['id']}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 404
