import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import engine
from app.models.webhook import Webhook
from app.schemas.webhook import WEBHOOK_EVENTS, WebhookCreate

logger = logging.getLogger(__name__)

# Webhook is disabled automatically after this many consecutive delivery
# failures. Prevents an unreachable endpoint from hammering us forever.
AUTO_DISABLE_THRESHOLD = 10
DELIVERY_TIMEOUT_SEC = 10
RETRY_SCHEDULE_SEC = (1, 5, 15)

# Sessionmaker for background delivery tasks that outlive the request that
# triggered them — we can't reuse the request-scoped AsyncSession because it
# closes as soon as the request completes.
_delivery_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


def sign_body(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def create_webhook(
    db: AsyncSession, user_id: UUID, payload: WebhookCreate
) -> tuple[Webhook, str]:
    invalid = [e for e in payload.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise ValueError(f"Unknown events: {', '.join(invalid)}")

    secret = secrets.token_urlsafe(32)
    row = Webhook(
        user_id=user_id,
        url=str(payload.url),
        events=payload.events,
        secret=secret,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, secret


async def list_user_webhooks(db: AsyncSession, user_id: UUID) -> list[Webhook]:
    result = await db.execute(
        select(Webhook)
        .where(Webhook.user_id == user_id)
        .order_by(Webhook.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_webhook(db: AsyncSession, user_id: UUID, webhook_id: UUID) -> bool:
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def _send_once(
    client: httpx.AsyncClient, hook: Webhook, event: str, body: bytes
) -> int:
    signature = sign_body(hook.secret, body)
    resp = await client.post(
        hook.url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-ArchFlow-Event": event,
            "X-ArchFlow-Signature": f"sha256={signature}",
        },
        timeout=DELIVERY_TIMEOUT_SEC,
    )
    return resp.status_code


async def _deliver_with_retry(webhook_id: UUID, event: str, body: bytes) -> None:
    """Re-open a DB session, attempt delivery, record status + auto-disable
    after enough consecutive failures."""
    async with _delivery_sessionmaker() as db:
        result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
        hook = result.scalar_one_or_none()
        if hook is None or not hook.enabled:
            return

        status: int | None = None
        async with httpx.AsyncClient() as client:
            for attempt, delay in enumerate(RETRY_SCHEDULE_SEC):
                try:
                    status = await _send_once(client, hook, event, body)
                    if 200 <= status < 300:
                        break
                except Exception as e:  # network error, timeout, etc.
                    logger.warning(
                        "webhook %s delivery attempt %d failed: %s",
                        hook.id,
                        attempt + 1,
                        e,
                    )
                    status = None
                if attempt < len(RETRY_SCHEDULE_SEC) - 1:
                    await asyncio.sleep(delay)

        hook.last_delivery_at = datetime.now(UTC)
        hook.last_status = status
        if status is None or status >= 400:
            hook.failure_count = hook.failure_count + 1
            if hook.failure_count >= AUTO_DISABLE_THRESHOLD:
                hook.enabled = False
        else:
            hook.failure_count = 0
        await db.commit()


def _emit_sync_dispatch(event: str, payload: dict[str, Any], hook_ids: list[UUID]) -> None:
    body = json.dumps({"event": event, "data": payload}, default=str).encode()
    for hook_id in hook_ids:
        asyncio.create_task(_deliver_with_retry(hook_id, event, body))


async def emit(db: AsyncSession, event: str, payload: dict[str, Any]) -> None:
    """Fan-out `event` to every enabled webhook subscribed to it.

    Delivery is scheduled as background tasks so the caller's request isn't
    blocked on outbound HTTP. Must tolerate delivery errors silently —
    webhooks are a best-effort side channel.
    """
    try:
        result = await db.execute(
            select(Webhook).where(
                Webhook.enabled == True,  # noqa: E712
                Webhook.events.any(event),
            )
        )
        hook_ids = [h.id for h in result.scalars().all()]
    except Exception:
        logger.exception("webhook fan-out lookup failed for %s", event)
        return
    if not hook_ids:
        return
    _emit_sync_dispatch(event, payload, hook_ids)


def fire_and_forget_emit(event: str, payload: dict[str, Any]) -> None:
    """Convenience wrapper: open a short-lived session, call emit, swallow.

    Use when a service function doesn't already have an AsyncSession handy,
    or when emitting after a db.commit() that ended the request session.
    """
    async def _go() -> None:
        async with _delivery_sessionmaker() as db:
            await emit(db, event, payload)

    asyncio.create_task(_go())
