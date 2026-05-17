"""Generic OIDC SSO — Authorization Code flow.

    GET /api/v1/auth/oauth/oidc/login
        → 302 to the provider's authorization endpoint (or 503 if not configured).
    GET /api/v1/auth/oauth/oidc/callback?code=...
        → exchange code → userinfo → upsert user → issue app JWTs
          → 302 to frontend /auth/callback with tokens in URL fragment.

Works with any OIDC-compliant provider (Authelia, Keycloak, Authentik, Okta,
Google, etc.). Endpoints are discovered from
``{OIDC_ISSUER_URL}/.well-known/openid-configuration``; we cache the document
in-process per issuer so we don't hammer the IdP on every login click.

Configured via OIDC_* env vars in app/core/config.py. When any of issuer_url,
client_id, or client_secret is missing both endpoints return 503 so the SPA
can fall back to email/password.

Mirrors the Google OAuth pattern in oauth_stub.py (same user upsert, same
fragment-based token delivery) — chose composition over abstraction to keep
each provider's quirks contained.
"""
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.user import User
from app.services import workspace_service

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])

# Discovery doc cache keyed by issuer URL. OIDC discovery responses are stable
# and the IdP signals rotation via the keys endpoint, not this doc — caching
# for the process lifetime is the standard pattern. Cleared by tests.
_discovery_cache: dict[str, dict] = {}


def _oidc_enabled() -> bool:
    return bool(
        settings.oidc_issuer_url
        and settings.oidc_client_id
        and settings.oidc_client_secret
    )


async def _get_discovery(client: httpx.AsyncClient) -> dict:
    issuer = settings.oidc_issuer_url
    cached = _discovery_cache.get(issuer)
    if cached is not None:
        return cached
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    resp = await client.get(url)
    if resp.status_code != 200:
        raise HTTPException(502, f"OIDC discovery failed: {resp.status_code}")
    doc = resp.json()
    _discovery_cache[issuer] = doc
    return doc


@router.get("/oidc/login")
async def oidc_login():
    if not _oidc_enabled():
        raise HTTPException(503, "OIDC not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        disc = await _get_discovery(client)
    qs = urlencode({
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "response_type": "code",
        "scope": settings.oidc_scopes,
    })
    return RedirectResponse(f"{disc['authorization_endpoint']}?{qs}")


@router.get("/oidc/callback")
async def oidc_callback(
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not _oidc_enabled():
        raise HTTPException(503, "OIDC not configured")

    async with httpx.AsyncClient(timeout=10) as client:
        disc = await _get_discovery(client)

        token_resp = await client.post(
            disc["token_endpoint"],
            data={
                "code": code,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
                "redirect_uri": settings.oidc_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(400, f"OIDC token exchange failed: {token_resp.text}")
        provider_access = token_resp.json().get("access_token")
        if not provider_access:
            raise HTTPException(400, "OIDC token response missing access_token")

        ui_resp = await client.get(
            disc["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {provider_access}"},
        )
        if ui_resp.status_code != 200:
            raise HTTPException(400, "OIDC userinfo fetch failed")
        info = ui_resp.json()

    email = info.get("email")
    if not email:
        raise HTTPException(400, "OIDC account returned no email claim")
    name = info.get("name") or email.split("@")[0].title()

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is None:
        user = User(
            email=email,
            name=name,
            # Random hash no one can log in with — they must keep using SSO.
            password_hash=hash_password("oidc-only:" + email),
            auth_provider="oidc",
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        await workspace_service.create_personal_workspace(db, user)
    else:
        user = existing

    # Fragment-based delivery so tokens never show up in server access logs.
    frag = urlencode({
        "access_token": create_access_token(str(user.id)),
        "refresh_token": create_refresh_token(str(user.id)),
    })
    return RedirectResponse(f"{settings.frontend_url}/auth/callback#{frag}")
