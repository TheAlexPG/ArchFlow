import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import Comment, CommentTargetType
from app.schemas.comment import CommentCreate, CommentUpdate


async def list_comments(
    db: AsyncSession,
    target_type: CommentTargetType,
    target_id: uuid.UUID,
) -> list[Comment]:
    result = await db.execute(
        select(Comment)
        .where(
            Comment.target_type == target_type,
            Comment.target_id == target_id,
        )
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.asc())
    )
    return list(result.scalars().all())


async def get_comment(db: AsyncSession, comment_id: uuid.UUID) -> Comment | None:
    result = await db.execute(
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )
    return result.scalar_one_or_none()


async def create_comment(
    db: AsyncSession,
    data: CommentCreate,
    author_id: uuid.UUID | None = None,
) -> Comment:
    comment = Comment(
        target_type=data.target_type,
        target_id=data.target_id,
        comment_type=data.comment_type,
        body=data.body,
        position_x=data.position_x,
        position_y=data.position_y,
        author_id=author_id,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment, attribute_names=["author"])
    return comment


async def update_comment(
    db: AsyncSession, comment: Comment, data: CommentUpdate
) -> Comment:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comment, field, value)
    await db.flush()
    await db.refresh(comment, attribute_names=["author"])
    return comment


async def delete_comment(db: AsyncSession, comment: Comment) -> None:
    await db.delete(comment)
    await db.flush()
