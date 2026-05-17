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

Implementation notes
--------------------
* respx is scoped to ``base_url=ISSUER`` so it ONLY intercepts outbound calls
  to the fake provider. Without that scope, respx swallows the test client's
  ASGI requests too and the tests hang indefinitely on CI.
* The HTTP-level tests do NOT take the ``db`` fixture. Holding the fixture's
  session open while the ASGI handler opens its own via ``get_db`` causes the
  in-test verification query to either deadlock or read stale data. Instead
  we open a fresh ``async_session`` after the call to assert on DB state.
"""
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import respx
from httpx import Response
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ISSUER = "https://auth.example.com"
DISCOVERY_PATH = "/.well-known/openid-configuration"
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
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:5173")
    # Discovery cache is keyed on issuer; clear it so each test sees a fresh
    # fetch path.
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


def _mock_provider(router, *, token_status: int = 200, userinfo: dict | None = None):
    """Register the three OIDC endpoints on the passed respx router.

    Routes must be added to the scoped router instance returned by
    ``respx.mock(base_url=...)`` — the module-level ``respx.get(...)`` adds
    to the global default router, which is a different object and won't
    intercept the scoped requests.
    """
    router.get(DISCOVERY_PATH).mock(
        return_value=Response(200, json=_discovery_doc())
    )
    if token_status == 200:
        router.post(TOKEN_URL).mock(
            return_value=Response(200, json={"access_token": "provider-access"})
        )
    else:
        router.post(TOKEN_URL).mock(
            return_value=Response(token_status, json={"error": "invalid_grant"})
        )
    if userinfo is not None:
        router.get(USERINFO_URL).mock(return_value=Response(200, json=userinfo))


async def _fetch_user_by_email(email: str) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


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


async def test_oidc_login_redirects_to_authorization_endpoint(
    client, oidc_enabled
):
    """Login fetches discovery and 302s to the provider's authorize URL with
    the expected OAuth2/OIDC query params."""
    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        router.get(DISCOVERY_PATH).mock(
            return_value=Response(200, json=_discovery_doc())
        )

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


async def test_oidc_callback_creates_new_user_and_returns_tokens(
    client, oidc_enabled
):
    """Happy path: code → tokens → userinfo → upsert → 302 with app JWTs in
    URL fragment. New user gets auth_provider=oidc + a personal workspace."""
    # Unique email per test run so we don't depend on table-truncation order.
    new_email = f"oidc-new-{uuid.uuid4().hex[:10]}@example.com"

    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        _mock_provider(
            router,
            userinfo={
                "sub": "auth0|abc123",
                "email": new_email,
                "email_verified": True,
                "name": "New OIDC User",
            },
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
    assert frag_params["access_token"][0]  # non-empty
    assert frag_params["refresh_token"][0]

    # User row created with oidc provider tag (verified via a fresh session
    # because the ASGI handler runs its own).
    user = await _fetch_user_by_email(new_email)
    assert user is not None
    assert user.auth_provider == "oidc"
    assert user.name == "New OIDC User"


async def test_oidc_callback_reuses_existing_user_by_email(
    client, oidc_enabled
):
    """If a user with the OIDC-returned email already exists, callback returns
    tokens for that user instead of erroring on the unique-email constraint."""
    # Seed an existing user via a fresh session, then verify the callback
    # doesn't try to insert a duplicate.
    existing_email = f"oidc-existing-{uuid.uuid4().hex[:10]}@example.com"
    async with async_session() as session:
        u = User(
            email=existing_email,
            name="Existing User",
            password_hash="x",
            auth_provider="local",
        )
        session.add(u)
        await session.commit()
        existing_id = u.id

    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        _mock_provider(
            router,
            userinfo={
                "sub": "x",
                "email": existing_email,
                "email_verified": True,
                "name": "Existing User",
            },
        )

        resp = await client.get(
            "/api/v1/auth/oauth/oidc/callback?code=test-code",
            follow_redirects=False,
        )

    assert resp.status_code in (302, 307)

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.email == existing_email)
        )
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].id == existing_id


async def test_oidc_callback_rejects_userinfo_without_email(
    client, oidc_enabled
):
    """Provider must return an email claim — anything else is rejected with
    400 rather than creating a userless row."""
    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        _mock_provider(router, userinfo={"sub": "x"})  # no email

        resp = await client.get(
            "/api/v1/auth/oauth/oidc/callback?code=test-code",
            follow_redirects=False,
        )

    assert resp.status_code == 400


async def test_oidc_callback_propagates_token_endpoint_failure(
    client, oidc_enabled
):
    """If the token exchange fails the user sees a 400 rather than a 500 —
    callback must surface provider errors instead of crashing."""
    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        _mock_provider(router, token_status=400)

        resp = await client.get(
            "/api/v1/auth/oauth/oidc/callback?code=bad-code",
            follow_redirects=False,
        )

    assert resp.status_code == 400


async def test_oidc_callback_rejects_unverified_email(client, oidc_enabled):
    """email_verified=false must be rejected — otherwise an attacker with
    control of any IdP could claim someone else's email and take over a
    pre-existing local account in the upsert path. Default-deny: missing
    claim is treated the same as explicit false."""
    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        _mock_provider(
            router,
            userinfo={
                "sub": "x",
                "email": "victim@example.com",
                "email_verified": False,
                "name": "Attacker",
            },
        )

        resp = await client.get(
            "/api/v1/auth/oauth/oidc/callback?code=test-code",
            follow_redirects=False,
        )

    assert resp.status_code == 400
    # Sanity: no user row created.
    user = await _fetch_user_by_email("victim@example.com")
    assert user is None


async def test_oidc_discovery_doc_missing_endpoints_returns_502(
    client, oidc_enabled
):
    """If the IdP's discovery doc is missing a required endpoint we must
    fail at discovery (502) rather than throw KeyError downstream."""
    bad_doc = {"issuer": ISSUER}  # no *_endpoint fields

    with respx.mock(base_url=ISSUER, assert_all_called=False) as router:
        router.get(DISCOVERY_PATH).mock(return_value=Response(200, json=bad_doc))

        resp = await client.get(
            "/api/v1/auth/oauth/oidc/login", follow_redirects=False
        )

    assert resp.status_code == 502
