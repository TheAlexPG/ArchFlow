import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.services.api_key_service import KEY_PREFIX, verify_api_key


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.split(" ", 1)[1]

    # API key path — detected by the "ak_" prefix. Bypasses JWT decoding and
    # resolves the owning user directly.
    if token.startswith(KEY_PREFIX):
        api_key = await verify_api_key(db, token)
        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        request.state.api_key = api_key
        result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_optional_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


async def get_current_workspace_id(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> uuid.UUID | None:
    """
    Resolve the workspace the caller is currently operating in.

    Reads the X-Workspace-ID header and validates that the caller is a
    member. Falls back to the user's default workspace if the header is
    missing/invalid. Returns None for unauthenticated callers or when the
    user has no workspaces yet.
    """
    if current_user is None:
        return None
    # Local import to avoid a circular import at module load time
    # (workspace_service imports from app.models which imports app.api.deps
    # transitively via other paths during test collection).
    from app.services import workspace_service

    header_value = request.headers.get("X-Workspace-ID")
    if header_value:
        try:
            candidate = uuid.UUID(header_value)
        except ValueError:
            candidate = None
        if candidate is not None:
            membership = await workspace_service.get_user_membership(
                db, current_user.id, candidate
            )
            if membership is not None:
                return candidate
    ws = await workspace_service.get_default_workspace_for_user(db, current_user.id)
    return ws.id if ws else None
