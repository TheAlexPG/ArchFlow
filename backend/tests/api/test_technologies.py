"""Integration tests for the technology catalog REST API.

These tests run against the live dev database; they require the
`technologies` table migration (c0dbe5b00001) and the activity-log enum
extension (c0dbe5b00002) to have been applied. They assume the built-in
seed has been loaded (the migration handles that).
"""
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
    assert r.status_code == 200, r.text
    return r.json()[0]["id"]


async def _invite_as(client, owner_auth, ws_id, email, role):
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": email, "role": role},
        headers=owner_auth,
    )
    assert r.status_code == 201, r.text
    invite_id = r.json()["invite"]["id"]
    r2 = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "s3cret-pw!"},
    )
    token = r2.json()["access_token"]
    await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


# ─── List / search ─────────────────────────────────────────────

async def test_list_includes_builtin_seed(client):
    token, _ = await _register(client, "techA")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(f"/api/v1/workspaces/{ws_id}/technologies", headers=auth)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) >= 100, "built-in seed should yield many rows"

    slugs = {it["slug"] for it in items}
    for expected in {"postgresql", "fastapi", "figma", "grpc"}:
        assert expected in slugs


async def test_scope_builtin_excludes_custom(client):
    token, _ = await _register(client, "techB")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    # Create a custom
    await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "AcmeCorp Billing",
            "iconify_name": "logos:python",
            "category": "saas",
        },
        headers=auth,
    )

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?scope=builtin", headers=auth
    )
    slugs = {it["slug"] for it in r.json()}
    assert "acmecorp-billing" not in slugs


async def test_scope_custom_excludes_builtin(client):
    token, _ = await _register(client, "techC")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Only Custom",
            "iconify_name": "logos:python",
            "category": "tool",
        },
        headers=auth,
    )

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?scope=custom", headers=auth
    )
    items = r.json()
    for it in items:
        assert it["workspace_id"] == ws_id


async def test_filter_by_category(client):
    token, _ = await _register(client, "techD")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?category=protocol",
        headers=auth,
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) > 0
    for it in items:
        assert it["category"] == "protocol"


async def test_search_q_matches_aliases(client):
    token, _ = await _register(client, "techE")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?q=pg", headers=auth
    )
    slugs = {it["slug"] for it in r.json()}
    assert "postgresql" in slugs, "alias 'pg' should match PostgreSQL"


# ─── Create / edit / delete ───────────────────────────────────

async def test_create_custom_auto_slug(client):
    token, _ = await _register(client, "techF")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Acme Service!",
            "iconify_name": "logos:python",
            "category": "saas",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "acme-service"
    assert body["workspace_id"] == ws_id


async def test_create_custom_duplicate_slug_is_auto_suffixed(client):
    token, _ = await _register(client, "techG")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    payload = {
        "name": "Dupe",
        "iconify_name": "logos:python",
        "category": "tool",
    }
    r1 = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies", json=payload, headers=auth
    )
    r2 = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies", json=payload, headers=auth
    )
    assert r1.json()["slug"] == "dupe"
    assert r2.json()["slug"] == "dupe-2"


async def test_update_custom(client):
    token, _ = await _register(client, "techH")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Original",
            "iconify_name": "logos:python",
            "category": "tool",
        },
        headers=auth,
    )
    tech_id = r.json()["id"]

    r2 = await client.patch(
        f"/api/v1/workspaces/{ws_id}/technologies/{tech_id}",
        json={"name": "Renamed", "color": "#123456"},
        headers=auth,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "Renamed"
    assert r2.json()["color"] == "#123456"


async def test_cannot_update_builtin(client):
    token, _ = await _register(client, "techI")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?q=postgresql", headers=auth
    )
    builtin = next(it for it in r.json() if it["slug"] == "postgresql")

    r2 = await client.patch(
        f"/api/v1/workspaces/{ws_id}/technologies/{builtin['id']}",
        json={"name": "hacked"},
        headers=auth,
    )
    assert r2.status_code == 403, r2.text


async def test_cannot_delete_builtin(client):
    token, _ = await _register(client, "techJ")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?q=postgresql", headers=auth
    )
    builtin = next(it for it in r.json() if it["slug"] == "postgresql")

    r2 = await client.delete(
        f"/api/v1/workspaces/{ws_id}/technologies/{builtin['id']}", headers=auth
    )
    assert r2.status_code == 403, r2.text


async def test_delete_custom_without_refs(client):
    token, _ = await _register(client, "techK")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Trash Me",
            "iconify_name": "logos:python",
            "category": "tool",
        },
        headers=auth,
    )
    tech_id = r.json()["id"]

    r2 = await client.delete(
        f"/api/v1/workspaces/{ws_id}/technologies/{tech_id}", headers=auth
    )
    assert r2.status_code == 204

    # Now invisible in list
    r3 = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies?scope=custom", headers=auth
    )
    ids = {it["id"] for it in r3.json()}
    assert tech_id not in ids


async def test_cross_workspace_custom_not_visible(client):
    owner_a_token, _ = await _register(client, "techL-a")
    ws_a = await _workspace_id(client, owner_a_token)
    auth_a = {"Authorization": f"Bearer {owner_a_token}", "X-Workspace-ID": ws_a}

    owner_b_token, _ = await _register(client, "techL-b")
    ws_b = await _workspace_id(client, owner_b_token)
    auth_b = {"Authorization": f"Bearer {owner_b_token}", "X-Workspace-ID": ws_b}

    # A creates a custom
    await client.post(
        f"/api/v1/workspaces/{ws_a}/technologies",
        json={
            "name": "A's Tech",
            "iconify_name": "logos:python",
            "category": "tool",
        },
        headers=auth_a,
    )

    # B does not see it
    r = await client.get(
        f"/api/v1/workspaces/{ws_b}/technologies?scope=custom", headers=auth_b
    )
    slugs = {it["slug"] for it in r.json()}
    assert "a-s-tech" not in slugs


# ─── Permissions ───────────────────────────────────────────────

async def test_viewer_can_list_but_not_create(client):
    owner_token, _ = await _register(client, "techM-owner")
    ws_id = await _workspace_id(client, owner_token)
    owner_auth = {"Authorization": f"Bearer {owner_token}", "X-Workspace-ID": ws_id}

    _, viewer_email = await _register(client, "techM-viewer")
    viewer_token = await _invite_as(client, owner_auth, ws_id, viewer_email, "viewer")
    viewer_auth = {
        "Authorization": f"Bearer {viewer_token}",
        "X-Workspace-ID": ws_id,
    }

    r_list = await client.get(
        f"/api/v1/workspaces/{ws_id}/technologies", headers=viewer_auth
    )
    assert r_list.status_code == 200

    r_create = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Forbidden",
            "iconify_name": "logos:python",
            "category": "tool",
        },
        headers=viewer_auth,
    )
    assert r_create.status_code == 403


# ─── Validation ────────────────────────────────────────────────

async def test_invalid_iconify_name_rejected(client):
    token, _ = await _register(client, "techN")
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}

    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/technologies",
        json={
            "name": "Bad",
            "iconify_name": "Not Valid",
            "category": "tool",
        },
        headers=auth,
    )
    assert r.status_code == 422, r.text
