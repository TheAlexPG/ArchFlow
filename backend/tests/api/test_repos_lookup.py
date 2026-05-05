"""Tests for POST /api/v1/repos/lookup."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def with_secret_key(monkeypatch: pytest.MonkeyPatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("AGENTS_SECRET_KEY", key)
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", SecretStr(key))
    import importlib

    import app.services.secret_service as ss

    importlib.reload(ss)
    import app.services.workspace_service as ws_svc

    importlib.reload(ws_svc)


async def _register(client) -> tuple[str, str]:
    email = f"rl-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Lookup", "password": "s3cret-pw!"},
    )
    return r.json()["access_token"], email


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()[0]["id"]


async def _save_token(client, ws_id: str, auth: dict[str, str]) -> None:
    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value={"login": "octocat"}),
    ):
        r = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token",
            json={"token": "ghp_test"},
            headers=auth,
        )
        assert r.status_code == 200, r.text


async def test_lookup_repo_happy(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)
    await _save_token(client, ws_id, auth)

    fake_meta = {
        "full_name": "microsoft/typescript",
        "description": "TypeScript is a superset of JavaScript",
        "default_branch": "main",
        "stargazers_count": 99999,
        "private": False,
        "html_url": "https://github.com/microsoft/typescript",
    }
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(return_value=fake_meta),
    ):
        r = await client.post(
            "/api/v1/repos/lookup",
            json={"repo_url": "https://github.com/microsoft/typescript"},
            headers={**auth, "X-Workspace-ID": ws_id},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repo_url"] == "https://github.com/microsoft/typescript"
    assert body["full_name"] == "microsoft/typescript"
    assert body["default_branch"] == "main"
    assert body["description"].startswith("TypeScript")


async def test_lookup_repo_invalid_url(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)
    await _save_token(client, ws_id, auth)

    r = await client.post(
        "/api/v1/repos/lookup",
        json={"repo_url": "not-a-github-url"},
        headers={**auth, "X-Workspace-ID": ws_id},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "invalid_repo_url"


async def test_lookup_repo_without_token(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    r = await client.post(
        "/api/v1/repos/lookup",
        json={"repo_url": "https://github.com/microsoft/typescript"},
        headers={**auth, "X-Workspace-ID": ws_id},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "no_github_token"


async def test_lookup_repo_not_found(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)
    await _save_token(client, ws_id, auth)

    from app.services import repo_credentials_service

    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=repo_credentials_service.GitHubNotFoundError(
            "Repo gone"
        )),
    ):
        r = await client.post(
            "/api/v1/repos/lookup",
            json={"repo_url": "https://github.com/owner/missing"},
            headers={**auth, "X-Workspace-ID": ws_id},
        )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "not_found"


async def test_lookup_repo_unauthorized(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)
    await _save_token(client, ws_id, auth)

    from app.services import repo_credentials_service

    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(side_effect=repo_credentials_service.GitHubAuthError(
            "rejected"
        )),
    ):
        r = await client.post(
            "/api/v1/repos/lookup",
            json={"repo_url": "https://github.com/owner/repo"},
            headers={**auth, "X-Workspace-ID": ws_id},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "unauthorized"


async def test_lookup_accepts_ssh_form(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)
    await _save_token(client, ws_id, auth)

    fake_meta = {
        "full_name": "owner/repo",
        "description": None,
        "default_branch": "main",
    }
    with patch(
        "app.services.repo_credentials_service.lookup_repo",
        new=AsyncMock(return_value=fake_meta),
    ):
        r = await client.post(
            "/api/v1/repos/lookup",
            json={"repo_url": "git@github.com:owner/repo.git"},
            headers={**auth, "X-Workspace-ID": ws_id},
        )
    assert r.status_code == 200, r.text
    # SSH form gets normalised to canonical https URL.
    assert r.json()["repo_url"] == "https://github.com/owner/repo"
