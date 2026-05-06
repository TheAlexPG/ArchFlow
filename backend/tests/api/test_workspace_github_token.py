"""End-to-end tests for the workspace GitHub-token endpoints."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def with_secret_key(monkeypatch: pytest.MonkeyPatch):
    """Ensure secret_service has a Fernet key loaded for these tests."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("AGENTS_SECRET_KEY", key)
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", SecretStr(key))
    import importlib

    import app.services.secret_service as ss

    importlib.reload(ss)
    # Reload workspace_service so it picks up the patched secret_service.
    import app.services.workspace_service as ws_svc

    importlib.reload(ws_svc)
    return ss


async def _register(client, name: str = "GH Tester") -> tuple[str, str]:
    email = f"gh-{uuid.uuid4().hex[:10]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": "s3cret-pw!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], email


async def _workspace_id(client, token: str) -> str:
    r = await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    return r.json()[0]["id"]


def _fake_user_payload(login: str = "octocat") -> dict[str, Any]:
    return {"login": login, "id": 583231, "name": login.title()}


async def test_set_github_token_happy_path(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=_fake_user_payload("octocat")),
    ):
        r = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token",
            json={"token": "ghp_fake_pat_value_12345"},
            headers=auth,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"linked": True, "github_login": "octocat"}

    # Verify it survived persistence — call test endpoint without a body
    # (uses the stored token).
    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=_fake_user_payload("octocat")),
    ):
        r2 = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token/test",
            json={},
            headers=auth,
        )
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"linked": True, "github_login": "octocat"}


async def test_set_github_token_invalid_returns_422(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=None),  # 401 from GitHub
    ):
        r = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token",
            json={"token": "ghp_invalid"},
            headers=auth,
        )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid_token"


async def test_clear_github_token(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    # Save a token first.
    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=_fake_user_payload()),
    ):
        await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token",
            json={"token": "ghp_a"},
            headers=auth,
        )

    # Clear.
    r = await client.delete(
        f"/api/v1/workspaces/{ws_id}/github-token", headers=auth
    )
    assert r.status_code == 204, r.text

    # Test endpoint should now report unlinked, no upstream call.
    r2 = await client.post(
        f"/api/v1/workspaces/{ws_id}/github-token/test",
        json={},
        headers=auth,
    )
    assert r2.status_code == 200
    assert r2.json() == {"linked": False, "github_login": None}


async def test_test_endpoint_with_explicit_token(client):
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=_fake_user_payload("explicit-user")),
    ):
        r = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token/test",
            json={"token": "ghp_explicit"},
            headers=auth,
        )
    assert r.status_code == 200
    assert r.json() == {"linked": True, "github_login": "explicit-user"}


async def test_non_owner_forbidden(client):
    """Editor / viewer roles cannot set the workspace's token."""
    owner_token, _ = await _register(client, name="Owner")
    ws_id = await _workspace_id(client, owner_token)

    intruder_token, _ = await _register(client, name="Intruder")

    # Intruder is not even a member — must 404.
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/github-token",
        json={"token": "ghp_x"},
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert r.status_code == 404


async def test_round_trip_through_workspace_service(client):
    """Set → fetch back via workspace_service.get_github_token.

    Closes the loop: encryption persists the actual plaintext value, not
    a fixture mock.
    """
    token, _ = await _register(client)
    auth = {"Authorization": f"Bearer {token}"}
    ws_id = await _workspace_id(client, token)

    with patch(
        "app.services.repo_credentials_service.validate_token",
        new=AsyncMock(return_value=_fake_user_payload()),
    ):
        r = await client.post(
            f"/api/v1/workspaces/{ws_id}/github-token",
            json={"token": "ghp_round_trip_value"},
            headers=auth,
        )
    assert r.status_code == 200, r.text

    from app.core.database import async_session
    from app.services import workspace_service

    async with async_session() as s:
        plaintext = await workspace_service.get_github_token(
            s, uuid.UUID(ws_id)
        )
    assert plaintext == "ghp_round_trip_value"
