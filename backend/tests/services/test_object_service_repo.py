"""Tests for repo_url normalisation + type validation in object_service."""
from __future__ import annotations

import pytest

from app.models.object import ObjectType
from app.services import object_service


@pytest.mark.parametrize(
    "input_url,expected_canonical",
    [
        ("https://github.com/octocat/Hello-World", "https://github.com/octocat/Hello-World"),
        ("https://github.com/octocat/Hello-World/", "https://github.com/octocat/Hello-World"),
        ("https://github.com/octocat/Hello-World.git", "https://github.com/octocat/Hello-World"),
        ("git@github.com:octocat/Hello-World.git", "https://github.com/octocat/Hello-World"),
        ("git@github.com:octocat/Hello-World", "https://github.com/octocat/Hello-World"),
        ("http://github.com/octocat/Hello-World", "https://github.com/octocat/Hello-World"),
    ],
)
def test_normalize_repo_url_accepts(input_url: str, expected_canonical: str):
    canonical, full = object_service.normalize_repo_url(input_url)
    assert canonical == expected_canonical
    assert full == "octocat/Hello-World"


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "not-a-url",
        "https://gitlab.com/owner/repo",
        "https://github.com/just-owner",
        "github.com/owner/repo",  # missing scheme + not SSH form
        "ssh://git@github.com/owner/repo",
    ],
)
def test_normalize_repo_url_rejects(bad_url: str):
    with pytest.raises(object_service.InvalidRepoUrlError):
        object_service.normalize_repo_url(bad_url)


def test_is_repo_linkable_matrix():
    assert object_service._is_repo_linkable(ObjectType.SYSTEM)
    assert object_service._is_repo_linkable(ObjectType.APP)
    assert object_service._is_repo_linkable(ObjectType.STORE)
    # Group is L2 conceptually but it's just a logical bucket — repos
    # don't attach to it per spec.
    assert not object_service._is_repo_linkable(ObjectType.GROUP)
    assert not object_service._is_repo_linkable(ObjectType.COMPONENT)
    assert not object_service._is_repo_linkable(ObjectType.ACTOR)
    assert not object_service._is_repo_linkable(ObjectType.EXTERNAL_SYSTEM)
    # String forms also accepted.
    assert object_service._is_repo_linkable("system")
    assert object_service._is_repo_linkable("app")
    assert not object_service._is_repo_linkable("component")
    assert not object_service._is_repo_linkable("nonsense")


# ---------------------------------------------------------------------------
# Endpoint-level: 422 on non-Container/System types
# ---------------------------------------------------------------------------


import uuid  # noqa: E402


async def _register(client) -> tuple[str, str]:
    email = f"orepo-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "RepoTest", "password": "s3cret-pw!"},
    )
    return r.json()["access_token"], email


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()[0]["id"]


async def test_create_object_with_repo_url_on_container_succeeds(client):
    token, _ = await _register(client)
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    r = await client.post(
        "/api/v1/objects",
        json={
            "name": "Backend API",
            "type": "app",
            "repo_url": "git@github.com:my-org/backend.git",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Normalised on storage.
    assert body["repo_url"] == "https://github.com/my-org/backend"
    assert body["repo_branch"] is None


async def test_create_object_with_repo_url_on_component_rejected(client):
    token, _ = await _register(client)
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    r = await client.post(
        "/api/v1/objects",
        json={
            "name": "Component A",
            "type": "component",
            "repo_url": "https://github.com/owner/repo",
        },
        headers=auth,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "repo_link_not_allowed"


async def test_create_object_with_invalid_repo_url_returns_422(client):
    token, _ = await _register(client)
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    r = await client.post(
        "/api/v1/objects",
        json={
            "name": "System X",
            "type": "system",
            "repo_url": "https://gitlab.com/x/y",
        },
        headers=auth,
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_repo_url"


async def test_update_object_clearing_repo_url(client):
    token, _ = await _register(client)
    ws_id = await _workspace_id(client, token)
    auth = {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}
    r = await client.post(
        "/api/v1/objects",
        json={
            "name": "ToClear",
            "type": "system",
            "repo_url": "https://github.com/o/r",
            "repo_branch": "main",
        },
        headers=auth,
    )
    assert r.status_code == 201
    obj_id = r.json()["id"]

    r = await client.put(
        f"/api/v1/objects/{obj_id}",
        json={"repo_url": None},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_url"] is None
    # Branch must drop along with the URL — it has no meaning otherwise.
    assert body["repo_branch"] is None
