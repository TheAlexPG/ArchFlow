from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.webhook import (
    WEBHOOK_EVENTS,
    WebhookCreate,
    WebhookResponse,
    WebhookWithSecret,
)
from app.services import webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/events", response_model=list[str])
async def list_event_types():
    return WEBHOOK_EVENTS


@router.post("", response_model=WebhookWithSecret, status_code=201)
async def create_webhook(
    payload: WebhookCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        row, secret = await webhook_service.create_webhook(db, current_user.id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return WebhookWithSecret(
        id=row.id,
        url=row.url,
        events=row.events,
        enabled=row.enabled,
        failure_count=row.failure_count,
        last_delivery_at=row.last_delivery_at,
        last_status=row.last_status,
        created_at=row.created_at,
        secret=secret,
    )


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await webhook_service.list_user_webhooks(db, current_user.id)
    return [WebhookResponse.model_validate(r) for r in rows]


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await webhook_service.delete_webhook(db, current_user.id, webhook_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Webhook not found")


@router.post("/{webhook_id}/test", status_code=202)
async def test_webhook(
    webhook_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a synthetic ping so the user can validate their endpoint."""
    from sqlalchemy import select

    from app.models.webhook import Webhook

    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id, Webhook.user_id == current_user.id
        )
    )
    hook = result.scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    webhook_service.fire_and_forget_emit("webhook.ping", {"webhook_id": str(hook.id)})
    return {"queued": True}
