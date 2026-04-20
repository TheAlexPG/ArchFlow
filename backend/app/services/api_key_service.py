import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate

# Every key starts with this so we can cheaply detect "this Bearer is an API
# key, not a JWT" in the auth dependency.
KEY_PREFIX = "ak_"
# Length of the prefix portion we persist + show in listings. Long enough to
# be unique across a single org, short enough to fit on one line.
PREFIX_LEN = 12


def _generate_plaintext() -> tuple[str, str]:
    """Return (full_secret, prefix). Prefix is persisted; full is not."""
    random_part = secrets.token_urlsafe(32)
    full = f"{KEY_PREFIX}{random_part}"
    return full, full[:PREFIX_LEN]


async def create_api_key(
    db: AsyncSession, user_id: UUID, payload: ApiKeyCreate
) -> tuple[ApiKey, str]:
    secret, prefix = _generate_plaintext()
    expires_at = None
    if payload.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)

    row = ApiKey(
        user_id=user_id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=hash_password(secret),
        permissions=payload.permissions,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, secret


async def list_user_api_keys(db: AsyncSession, user_id: UUID) -> list[ApiKey]:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_key(
    db: AsyncSession, user_id: UUID, key_id: UUID
) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row or row.revoked_at is not None:
        return row
    row.revoked_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return row


async def verify_api_key(db: AsyncSession, secret: str) -> ApiKey | None:
    """Resolve a plaintext Bearer secret to an ApiKey row, or None if invalid.

    Also updates last_used_at on success.
    """
    if not secret.startswith(KEY_PREFIX):
        return None
    prefix = secret[:PREFIX_LEN]
    result = await db.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(UTC):
        return None
    if not verify_password(secret, row.key_hash):
        return None
    row.last_used_at = datetime.now(UTC)
    await db.commit()
    return row
