"""Google OAuth — Authorization Code flow.

    GET /api/v1/auth/oauth/google/login
        → 302 to Google consent screen (or 503 if creds not configured).
    GET /api/v1/auth/oauth/google/callback?code=...
        → exchange code → userinfo → upsert user → issue app JWTs
          → 302 to frontend /auth/callback with tokens in URL fragment.

Client creds live in /srv/archflow/.env (GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, FRONTEND_URL). When any is
missing both endpoints return 503 so the SPA can fall back to email/password.
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

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _oauth_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


@router.get("/google/login")
async def login():
    if not _oauth_enabled():
        raise HTTPException(503, "Google OAuth not configured")
    qs = urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
    })
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{qs}")


@router.get("/google/callback")
async def callback(
    code: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not _oauth_enabled():
        raise HTTPException(503, "Google OAuth not configured")

    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(400, f"Google token exchange failed: {token_resp.text}")
        google_access = token_resp.json().get("access_token")

        ui_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access}"},
        )
        if ui_resp.status_code != 200:
            raise HTTPException(400, "Google userinfo fetch failed")
        info = ui_resp.json()

    email = info.get("email")
    if not email:
        raise HTTPException(400, "Google account returned no email")
    name = info.get("name") or email.split("@")[0].title()

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is None:
        user = User(
            email=email,
            name=name,
            # Random hash no one can log in with — they must keep using Google.
            password_hash=hash_password("oauth-only:" + email),
            auth_provider="google",
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
