"""Tests for GET /api/v1/agents/settings and PUT /api/v1/agents/settings.

Covers:
- Admin-only access (403 for editor)
- has_key=False when no api_key, True when set
- PUT updates litellm provider + model_default
- PUT api_key=null clears it
- PUT api_key=string encrypts before write (encrypted bytes in DB, not plaintext)
- PUT analytics_consent='full'
- PUT model_pricing.{model_id}.input_per_million
- Deep merge preserves unchanged fields
- Audit log written without raw secret values
"""
from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.activity_log import ActivityLog, ActivityTargetType
from app.models.workspace_agent_setting import WorkspaceAgentSetting
from app.services import secret_service

# ---------------------------------------------------------------------------
# Module-level fixture: inject AGENTS_SECRET_KEY so encryption is available
# ---------------------------------------------------------------------------

_FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def inject_secret_key(monkeypatch: pytest.MonkeyPatch):
    """Inject a valid AGENTS_SECRET_KEY into config for every test in this module."""
    from app.core import config as cfg_module

    monkeypatch.setattr(
        cfg_module.settings, "agents_secret_key", SecretStr(_FERNET_KEY)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register(client: AsyncClient, tag: str = "s") -> tuple[str, str]:
    """Register a user and return (token, workspace_id)."""
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": f"{tag.title()} Tester", "password": "pw!test"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    ws_list = (
        await client.get(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    ws_id = ws_list[0]["id"]
    return token, ws_id


async def _invite_and_accept(
    client: AsyncClient,
    owner_token: str,
    ws_id: str,
    role: str,
) -> str:
    """Invite a new user with given role to workspace and return their token."""
    email = f"inv-{uuid.uuid4().hex[:8]}@example.com"
    # Register the invited user first
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Invitee", "password": "pw!test"},
    )
    assert r.status_code == 201, r.text
    invitee_token = r.json()["access_token"]

    # Owner invites them
    r = await client.post(
        f"/api/v1/workspaces/{ws_id}/invites",
        json={"email": email, "role": role},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert r.status_code == 201, r.text
    invite_id = r.json()["invite"]["id"]

    # Invitee accepts
    r = await client.post(
        f"/api/v1/me/invites/{invite_id}/accept",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )
    assert r.status_code == 200, r.text
    return invitee_token


def _auth(token: str, ws_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Workspace-ID": ws_id}


async def _get_db_session() -> AsyncSession:
    async for db in get_db():
        return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_requires_admin_403_for_editor(client: AsyncClient):
    """Editor role must receive 403 on GET /agents/settings."""
    owner_token, ws_id = await _register(client, "a1")
    editor_token = await _invite_and_accept(client, owner_token, ws_id, "editor")

    r = await client.get(
        "/api/v1/agents/settings",
        headers=_auth(editor_token, ws_id),
    )
    assert r.status_code == 403, r.text


async def test_get_requires_admin_200_for_admin(client: AsyncClient):
    """Admin role must receive 200 on GET /agents/settings."""
    owner_token, ws_id = await _register(client, "a2")
    admin_token = await _invite_and_accept(client, owner_token, ws_id, "admin")

    r = await client.get(
        "/api/v1/agents/settings",
        headers=_auth(admin_token, ws_id),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "litellm" in body
    assert "has_key" in body["litellm"]


async def test_get_has_key_false_when_no_api_key(client: AsyncClient):
    """has_key must be False when no api_key is stored."""
    token, ws_id = await _register(client, "hk1")

    r = await client.get(
        "/api/v1/agents/settings",
        headers=_auth(token, ws_id),
    )
    assert r.status_code == 200, r.text
    assert r.json()["litellm"]["has_key"] is False


async def test_get_has_key_true_after_setting_api_key(client: AsyncClient):
    """has_key must be True after api_key is stored via PUT."""
    token, ws_id = await _register(client, "hk2")
    auth = _auth(token, ws_id)

    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"api_key": "sk-test-key-12345"}},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/agents/settings", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["litellm"]["has_key"] is True


async def test_put_updates_llm_provider_and_model(client: AsyncClient):
    """PUT updates litellm provider and model_default."""
    token, ws_id = await _register(client, "pu1")
    auth = _auth(token, ws_id)

    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"provider": "anthropic", "model_default": "claude-3-5-sonnet"}},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["litellm"]["provider"] == "anthropic"
    assert body["litellm"]["model_default"] == "claude-3-5-sonnet"


async def test_put_api_key_null_clears_key(client: AsyncClient):
    """Explicit api_key=null must clear a previously stored key."""
    token, ws_id = await _register(client, "pu2")
    auth = _auth(token, ws_id)

    # First set a key
    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"api_key": "sk-some-key"}},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["litellm"]["has_key"] is True

    # Now clear it
    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"api_key": None}},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["litellm"]["has_key"] is False


async def test_put_api_key_encrypts_before_write(client: AsyncClient):
    """api_key must be stored encrypted, not as plaintext."""
    token, ws_id = await _register(client, "pu3")
    auth = _auth(token, ws_id)
    plaintext_key = "sk-verysecretkey-9999"

    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"api_key": plaintext_key}},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    # Inspect the DB row directly.
    async for db in get_db():
        result = await db.execute(
            select(WorkspaceAgentSetting).where(
                WorkspaceAgentSetting.workspace_id == uuid.UUID(ws_id),
                WorkspaceAgentSetting.agent_id.is_(None),
                WorkspaceAgentSetting.key == "litellm_api_key",
            )
        )
        row = result.scalar_one_or_none()
        assert row is not None, "litellm_api_key row should exist"
        assert row.is_secret is True
        assert row.value_encrypted is not None
        # Must NOT be plaintext
        assert plaintext_key.encode() not in row.value_encrypted
        # Must decrypt back to plaintext
        assert secret_service.decrypt(row.value_encrypted) == plaintext_key
        break


async def test_put_analytics_consent(client: AsyncClient):
    """PUT analytics_consent='full' persists correctly."""
    token, ws_id = await _register(client, "pu4")
    auth = _auth(token, ws_id)

    r = await client.put(
        "/api/v1/agents/settings",
        json={"analytics_consent": "full"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["analytics_consent"] == "full"


async def test_put_model_pricing_override(client: AsyncClient):
    """PUT model_pricing.{model_id} stores and returns the override."""
    token, ws_id = await _register(client, "pu6")
    auth = _auth(token, ws_id)

    r = await client.put(
        "/api/v1/agents/settings",
        json={
            "model_pricing": {
                "openai/gpt-4o": {
                    "input_per_million": "5.50",
                    "output_per_million": "16.50",
                }
            }
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    pricing = r.json()["model_pricing"]
    assert "openai/gpt-4o" in pricing
    assert pricing["openai/gpt-4o"]["input_per_million"] == "5.50"
    assert pricing["openai/gpt-4o"]["output_per_million"] == "16.50"


async def test_put_preserves_unchanged_fields(client: AsyncClient):
    """PUT with partial body must not reset fields not mentioned in the request."""
    token, ws_id = await _register(client, "pu7")
    auth = _auth(token, ws_id)

    # Set provider first
    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"provider": "anthropic"}},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["litellm"]["provider"] == "anthropic"

    # Now update analytics_consent only — provider must remain "anthropic"
    r = await client.put(
        "/api/v1/agents/settings",
        json={"analytics_consent": "errors_only"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["litellm"]["provider"] == "anthropic"
    assert body["analytics_consent"] == "errors_only"


async def test_put_writes_audit_log_without_raw_secret(client: AsyncClient):
    """PUT must write an audit log entry; raw api_key must not appear in changes."""
    token, ws_id = await _register(client, "pu8")
    auth = _auth(token, ws_id)
    secret = "sk-audit-test-key-xyz"

    r = await client.put(
        "/api/v1/agents/settings",
        json={"litellm": {"api_key": secret, "provider": "openai"}},
        headers=auth,
    )
    assert r.status_code == 200, r.text

    # Inspect activity_log table for the audit entry.
    async for db in get_db():
        result = await db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.workspace_id == uuid.UUID(ws_id),
                ActivityLog.target_type == ActivityTargetType.WORKSPACE,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
        entry = result.scalar_one_or_none()
        assert entry is not None, "Audit log entry should have been written"
        changes = entry.changes or {}

        # The raw secret must not appear anywhere in the changes dict.
        import json
        changes_str = json.dumps(changes)
        assert secret not in changes_str, "Raw API key must not appear in audit log"

        # The api_key action must be noted.
        assert "litellm.api_key" in changes, "api_key action should be in changes"
        assert changes["litellm.api_key"] in (
            "litellm.api_key set",
            "litellm.api_key cleared",
        )

        # Provider update should appear in updated_keys.
        assert "litellm.provider" in changes.get("updated_keys", [])
        break
