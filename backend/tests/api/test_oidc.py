"""Tests for generic OIDC SSO login (Authelia, Keycloak, Authentik, etc.).

The flow mirrors the existing Google OAuth router in app/api/v1/oauth_stub.py
but is provider-agnostic — endpoints are discovered from
{OIDC_ISSUER_URL}/.well-known/openid-configuration and configured via:

    OIDC_ISSUER_URL          → e.g. https://auth.example.com
    OIDC_CLIENT_ID
    OIDC_CLIENT_SECRET
    OIDC_REDIRECT_URI        → backend callback
    OIDC_SCOPES              → defaults to "openid email profile"
    OIDC_PROVIDER_NAME       → display name shown on the login button

When any of the first three are missing both endpoints return 503 so the SPA
can fall back to email/password.
"""
from urllib.parse import parse_qs, urlparse

import pytest
import respx
from httpx import Response
from sqlalchemy import select

from app.core.config import settings
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ISSUER = "https://auth.example.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTH_URL = f"{ISSUER}/api/oidc/authorize"
TOKEN_URL = f"{ISSUER}/api/oidc/token"
USERINFO_URL = f"{ISSUER}/api/oidc/userinfo"


def _discovery_doc() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": AUTH_URL,
        "token_endpoint": TOKEN_URL,
        "userinfo_endpoint": USERINFO_URL,
    }


@pytest.fixture
def oidc_enabled(monkeypatch):
    """Configure OIDC settings so _oidc_enabled() returns True."""
    monkeypatch.setattr(settings, "oidc_issuer_url", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", "test-client-id")
    monkeypatch.setattr(settings, "oidc_client_secret", "test-client-secret")
    monkeypatch.setattr(
        settings,
        "oidc_redirect_uri",
        "http://localhost:8000/api/v1/auth/oauth/oidc/callback",
    )
    monkeypatch.setattr(settings, "oidc_scopes", "openid email profile")
    monkeypatch.setattr(settings, "oidc_provider_name", "Authelia")
    # Discovery cache must be reset between configs since it keys on issuer.
    from app.api.v1 import oidc as oidc_module

    oidc_module._discovery_cache.clear()
    yield
    oidc_module._discovery_cache.clear()


@pytest.fixture
def oidc_disabled(monkeypatch):
    """Force all OIDC settings to None so the feature is off."""
    monkeypatch.setattr(settings, "oidc_issuer_url", None)
    monkeypatch.setattr(settings, "oidc_client_id", None)
    monkeypatch.setattr(settings, "oidc_client_secret", None)


# ---------------------------------------------------------------------------
# /api/v1/auth/config
# ---------------------------------------------------------------------------


async def test_auth_config_when_oidc_disabled(client, oidc_disabled, monkeypatch):
    """Config endpoint reports OIDC off when issuer not set."""
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)

    resp = await client.get("/api/v1/auth/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["oidc_enabled"] is False
    assert body["google_enabled"] is False


async def test_auth_config_when_oidc_enabled(client, oidc_enabled):
    """Config endpoint reports OIDC on and surfaces the display name."""
    resp = await client.get("/api/v1/auth/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["oidc_enabled"] is True
    assert body["oidc_provider_name"] == "Authelia"


# ---------------------------------------------------------------------------
# /api/v1/auth/oauth/oidc/login
# ---------------------------------------------------------------------------


async def test_oidc_login_returns_503_when_not_configured(client, oidc_disabled):
    """Login endpoint is unavailable until OIDC creds are provisioned."""
    resp = await client.get(
        "/api/v1/auth/oauth/oidc/login", follow_redirects=False
    )
    assert resp.status_code == 503


@respx.mock
async def test_oidc_login_redirects_to_authorization_endpoint(
    client, oidc_enabled
):
    """Login fetches discovery and 302s to the provider's authorize URL with
    the expected OAuth2/OIDC query params."""
    respx.get(DISCOVERY_URL).mock(return_value=Response(200, json=_discovery_doc()))

    resp = await client.get(
        "/api/v1/auth/oauth/oidc/login", follow_redirects=False
    )

    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    parsed = urlparse(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTH_URL

    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["redirect_uri"] == [
        "http://localhost:8000/api/v1/auth/oauth/oidc/callback"
    ]
    assert qs["response_type"] == ["code"]
    assert "openid" in qs["scope"][0]


# ---------------------------------------------------------------------------
# /api/v1/auth/oauth/oidc/callback
# ---------------------------------------------------------------------------


async def test_oidc_callback_returns_503_when_not_configured(
    client, oidc_disabled
):
    resp = await client.get(
        "/api/v1/auth/oauth/oidc/callback?code=any", follow_redirects=False
    )
    assert resp.status_code == 503


@respx.mock
async def test_oidc_callback_creates_new_user_and_returns_tokens(
    client, db, oidc_enabled, monkeypatch
):
    """Happy path: code → tokens → userinfo → upsert → 302 with app JWTs in
    URL fragment. New user gets auth_provider=oidc + a personal workspace."""
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")

    # Clean slate — conftest's `db` fixture truncates `users`, so the email
    # we use below is guaranteed not to exist.
    new_email = "new-oidc-user@example.com"

    respx.get(DISCOVERY_URL).mock(return_value=Response(200, json=_discovery_doc()))
    respx.post(TOKEN_URL).mock(
        return_value=Response(
            200,
            json={
                "access_token": "provider-access-token",
                "id_token": "provider-id-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )
    respx.get(USERINFO_URL).mock(
        return_value=Response(
            200,
            json={
                "sub": "auth0|abc123",
                "email": new_email,
                "name": "New OIDC User",
            },
        )
    )

    resp = await client.get(
        "/api/v1/auth/oauth/oidc/callback?code=test-code",
        follow_redirects=False,
    )

    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith("http://localhost:5173/auth/callback#")
    fragment = location.split("#", 1)[1]
    frag_params = parse_qs(fragment)
    assert "access_token" in frag_params
    assert "refresh_token" in frag_params
    assert frag_params["access_token"][0]  # non-empty
    assert frag_params["refresh_token"][0]

    # User row created with oidc provider tag.
    result = await db.execute(select(User).where(User.email == new_email))
    user = result.scalar_one()
    assert user.auth_provider == "oidc"
    assert user.name == "New OIDC User"


@respx.mock
async def test_oidc_callback_reuses_existing_user_by_email(
    client, db, user, oidc_enabled, monkeypatch
):
    """If a user with the OIDC-returned email already exists, callback returns
    tokens for that user instead of erroring on the unique-email constraint."""
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")

    respx.get(DISCOVERY_URL).mock(return_value=Response(200, json=_discovery_doc()))
    respx.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "pa"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=Response(
            200, json={"sub": "x", "email": user.email, "name": user.name}
        )
    )

    resp = await client.get(
        "/api/v1/auth/oauth/oidc/callback?code=test-code",
        follow_redirects=False,
    )

    assert resp.status_code in (302, 307)

    # No duplicate row.
    result = await db.execute(select(User).where(User.email == user.email))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].id == user.id


@respx.mock
async def test_oidc_callback_rejects_userinfo_without_email(
    client, oidc_enabled
):
    """Provider must return an email claim — anything else is rejected with
    400 rather than creating a userless row."""
    respx.get(DISCOVERY_URL).mock(return_value=Response(200, json=_discovery_doc()))
    respx.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "pa"})
    )
    respx.get(USERINFO_URL).mock(
        return_value=Response(200, json={"sub": "x"})  # no email
    )

    resp = await client.get(
        "/api/v1/auth/oauth/oidc/callback?code=test-code",
        follow_redirects=False,
    )

    assert resp.status_code == 400


@respx.mock
async def test_oidc_callback_propagates_token_endpoint_failure(
    client, oidc_enabled
):
    """If the token exchange fails the user sees a 400 rather than a 500 —
    callback must surface provider errors instead of crashing."""
    respx.get(DISCOVERY_URL).mock(return_value=Response(200, json=_discovery_doc()))
    respx.post(TOKEN_URL).mock(
        return_value=Response(400, json={"error": "invalid_grant"})
    )

    resp = await client.get(
        "/api/v1/auth/oauth/oidc/callback?code=bad-code",
        follow_redirects=False,
    )

    assert resp.status_code == 400
