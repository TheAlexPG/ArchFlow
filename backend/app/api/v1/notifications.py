from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    target_url: str | None
    read_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await notification_service.list_for_user(db, current_user.id)
    return [
        NotificationResponse(
            id=r.id,
            kind=r.kind,
            title=r.title,
            body=r.body,
            target_url=r.target_url,
            read_at=r.read_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"count": await notification_service.unread_count(db, current_user.id)}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await notification_service.mark_read(db, current_user.id, notification_id)
    if not ok:
        raise HTTPException(404, "Not found")


@router.post("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    updated = await notification_service.mark_all_read(db, current_user.id)
    return {"updated": updated}
