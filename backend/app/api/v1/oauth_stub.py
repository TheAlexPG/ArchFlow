"""Google OAuth stub — wires up the endpoints the frontend expects, but does
not actually contact Google. Replace the `_mock_userinfo` helper and add real
client_id/secret config when the user flips this to live.

Flow:
  GET /api/v1/auth/oauth/google/login
      → returns the authorize URL (stub returns our callback directly).
  GET /api/v1/auth/oauth/google/callback?code=...
      → decodes the mock "code" (just an email pasted in), upserts the user
        with auth_provider='google', issues real JWT tokens, redirects to
        frontend with tokens in fragment.

When we wire the real Google client, only the two helper functions change —
endpoint shape stays identical for the frontend.
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.user import User
from app.services import workspace_service

router = APIRouter(prefix="/auth/oauth", tags=["oauth"])


def _mock_userinfo(code: str) -> dict:
    """Pretend Google told us who this is. The "code" is used verbatim as
    the email so tests + manual QA can pick any identity without real OAuth
    infrastructure."""
    return {"email": code, "name": code.split("@")[0].title()}


@router.get("/google/login")
async def login():
    """Real flow: 302 to https://accounts.google.com/o/oauth2/v2/auth?...

    Stub flow: return a URL pointing right back at our callback with a
    placeholder `code`. The frontend treats this like a real redirect URL.
    """
    qs = urlencode({"code": "stub-user@example.com"})
    return {
        "authorize_url": f"/api/v1/auth/oauth/google/callback?{qs}",
        "provider": "google",
        "stub": True,
    }


@router.get("/google/callback")
async def callback(
    code: str = Query(..., description="Google auth code (stub: used as email)"),
    db: AsyncSession = Depends(get_db),
):
    if "@" not in code:
        raise HTTPException(400, "Stub expects an email-shaped code")
    info = _mock_userinfo(code)

    existing = (
        await db.execute(select(User).where(User.email == info["email"]))
    ).scalar_one_or_none()

    if existing is None:
        user = User(
            email=info["email"],
            name=info["name"],
            # Random hash the user can never log into — they must use Google.
            password_hash=hash_password("oauth-only:" + info["email"]),
            auth_provider="google",
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        await workspace_service.create_personal_workspace(db, user)
    else:
        user = existing

    return {
        "access_token": create_access_token(str(user.id)),
        "refresh_token": create_refresh_token(str(user.id)),
        "is_new_user": existing is None,
        "stub": True,
    }
