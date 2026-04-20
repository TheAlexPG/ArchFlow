"""Notifications: persist + push over WebSocket.

We keep the model open-ended: `kind` is a string so new notification types
ship without a migration. Callers supply a short `title`, optional `body`,
and a `target_url` so clicking the bell navigates straight to the thing
that triggered it.
"""
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User
from app.realtime.manager import manager

MENTION_RE = re.compile(r"(?:^|\s)@([A-Za-z][\w.-]{1,62})")


async def create(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    target_url: str | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        target_url=target_url,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Let open tabs update the unread badge without polling.
    try:
        await manager.publish(
            f"user:{user_id}",
            {
                "type": "notification.new",
                "notification": {
                    "id": str(row.id),
                    "kind": row.kind,
                    "title": row.title,
                    "body": row.body,
                    "target_url": row.target_url,
                    "created_at": row.created_at.isoformat(),
                },
            },
        )
    except Exception:
        pass
    return row


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 50
) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(
            # Unread first, then newest.
            Notification.read_at.is_(None).desc(),
            Notification.created_at.desc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def mark_read(
    db: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await db.commit()
    return True


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    rows = list(result.scalars().all())
    now = datetime.now(UTC)
    for r in rows:
        r.read_at = now
    if rows:
        await db.commit()
    return len(rows)


def extract_mentions(text: str) -> list[str]:
    """Return the distinct @names found in `text`. Names are matched
    case-insensitively later against user.name + user.email local-part."""
    return list({m.lower() for m in MENTION_RE.findall(text or "")})


async def resolve_mentioned_users(
    db: AsyncSession, mentions: list[str]
) -> list[User]:
    if not mentions:
        return []
    # Match @foo against users whose name starts with "foo" (case-insensitive)
    # OR whose email local-part equals "foo". Keeps the query cheap and
    # deterministic; when two users share a first name the first-name
    # mention notifies both — good default for small teams.
    conditions = []
    for m in mentions:
        conditions.append(func.lower(User.email).like(f"{m}@%"))
        conditions.append(func.lower(User.name).like(f"{m}%"))
    from sqlalchemy import or_

    result = await db.execute(select(User).where(or_(*conditions)))
    return list(result.scalars().all())


async def notify_mentions_in_comment(
    db: AsyncSession,
    body: str,
    author_id: uuid.UUID | None,
    comment_id: uuid.UUID,
    target_url: str,
) -> None:
    """Parse @names from a comment body and create a notification for each
    distinct user. No-op if no mentions or all mentions resolve to the
    comment author (no self-notify)."""
    mentions = extract_mentions(body)
    if not mentions:
        return
    users = await resolve_mentioned_users(db, mentions)
    seen: set[uuid.UUID] = set()
    for u in users:
        if u.id in seen:
            continue
        if author_id is not None and u.id == author_id:
            continue
        seen.add(u.id)
        await create(
            db,
            user_id=u.id,
            kind="mention",
            title=f"You were mentioned",
            body=body[:280],
            target_url=target_url,
        )
