import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.models.comment import CommentTargetType
from app.models.user import User
from app.schemas.comment import CommentCreate, CommentResponse, CommentUpdate
from app.services import comment_service

router = APIRouter(prefix="/comments", tags=["comments"])


@router.get("", response_model=list[CommentResponse])
async def list_comments(
    target_type: CommentTargetType = Query(...),
    target_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await comment_service.list_comments(db, target_type, target_id)


@router.post("", response_model=CommentResponse, status_code=201)
async def create_comment(
    data: CommentCreate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    from app.services import notification_service

    author_id = user.id if user else None
    comment = await comment_service.create_comment(db, data, author_id=author_id)
    # Best-effort — don't fail the whole request if a mention resolution
    # blows up.
    try:
        target_url = _target_url_for_comment(data.target_type, data.target_id)
        await notification_service.notify_mentions_in_comment(
            db,
            body=data.body or "",
            author_id=author_id,
            comment_id=comment.id,
            target_url=target_url,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("mention notify failed")
    return comment


def _target_url_for_comment(
    target_type: CommentTargetType, target_id: uuid.UUID
) -> str:
    """Where clicking the notification should take the reader."""
    if target_type == CommentTargetType.DIAGRAM:
        return f"/diagram/{target_id}"
    if target_type == CommentTargetType.OBJECT:
        return f"/objects?focus={target_id}"
    return f"/connections?focus={target_id}"


@router.put("/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: uuid.UUID,
    data: CommentUpdate,
    db: AsyncSession = Depends(get_db),
):
    comment = await comment_service.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return await comment_service.update_comment(db, comment, data)


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    comment = await comment_service.get_comment(db, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    await comment_service.delete_comment(db, comment)
