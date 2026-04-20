from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyResponse, ApiKeyWithSecret
from app.services.api_key_service import (
    create_api_key,
    list_user_api_keys,
    revoke_api_key,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyWithSecret, status_code=201)
async def create_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row, secret = await create_api_key(db, current_user.id, payload)
    return ApiKeyWithSecret(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        permissions=row.permissions,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        secret=secret,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_user_api_keys(db, current_user.id)
    return [ApiKeyResponse.model_validate(r) for r in rows]


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await revoke_api_key(db, current_user.id, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return None
