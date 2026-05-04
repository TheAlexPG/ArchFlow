import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.comment import Comment, CommentTargetType
from app.schemas.comment import CommentCreate, CommentUpdate
from app.services import activity_service


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
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
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

    # Undo recording — gated on user's include_comments_in_undo toggle
    if (
        actor_user is not None
        and from_diagram_id is not None
        and workspace_id is not None
        and (actor_user.undo_settings or {}).get("include_comments_in_undo")
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=workspace_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.COMMENT,
            target_id=comment.id,
            action=UndoAction.CREATE,
            forward_summary=f"Added comment"[:80],
            inverse_payload={"target_id": str(comment.id)},
            after_state=activity_service.snapshot(comment),
            coalesce_key=f"comment:{comment.id}:create",
        )

    return comment


async def update_comment(
    db: AsyncSession,
    comment: Comment,
    data: CommentUpdate,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> Comment:
    before = activity_service.snapshot(comment)
    update_data = data.model_dump(exclude_unset=True)
    # Strip undo-context fields
    update_data.pop("from_diagram_id", None)
    update_data.pop("from_draft_id", None)
    for field, value in update_data.items():
        setattr(comment, field, value)
    await db.flush()
    await db.refresh(comment, attribute_names=["author"])
    after = activity_service.snapshot(comment)

    # Undo recording — gated on user's include_comments_in_undo toggle
    if (
        actor_user is not None
        and from_diagram_id is not None
        and workspace_id is not None
        and (actor_user.undo_settings or {}).get("include_comments_in_undo")
    ):
        diff = activity_service.diff_snapshots(before, after)
        if diff:
            from app.models.undo_entry import UndoAction, UndoTargetType
            from app.services import undo_service

            await undo_service.record(
                db,
                user_id=actor_user.id,
                workspace_id=workspace_id,
                diagram_id=from_diagram_id,
                draft_id=from_draft_id,
                target_type=UndoTargetType.COMMENT,
                target_id=comment.id,
                action=UndoAction.UPDATE,
                forward_summary=_summarise_comment_diff(comment, diff),
                inverse_payload={"before": {k: v["before"] for k, v in diff.items()}},
                after_state={k: v["after"] for k, v in diff.items()},
                coalesce_key=f"comment:{comment.id}:{','.join(sorted(diff.keys()))}",
            )

    return comment


async def delete_comment(
    db: AsyncSession,
    comment: Comment,
    *,
    actor_user=None,
    from_diagram_id: uuid.UUID | None = None,
    from_draft_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
) -> None:
    # Capture snapshot BEFORE delete
    snapshot = activity_service.snapshot(comment)
    comment_id = comment.id

    await db.delete(comment)
    await db.flush()

    # Undo recording — gated on user's include_comments_in_undo toggle
    if (
        actor_user is not None
        and from_diagram_id is not None
        and workspace_id is not None
        and (actor_user.undo_settings or {}).get("include_comments_in_undo")
    ):
        from app.models.undo_entry import UndoAction, UndoTargetType
        from app.services import undo_service

        await undo_service.record(
            db,
            user_id=actor_user.id,
            workspace_id=workspace_id,
            diagram_id=from_diagram_id,
            draft_id=from_draft_id,
            target_type=UndoTargetType.COMMENT,
            target_id=comment_id,
            action=UndoAction.DELETE,
            forward_summary=f"Deleted comment"[:80],
            inverse_payload={"snapshot": snapshot, "id": str(comment_id)},
            after_state=None,
            coalesce_key=f"comment:{comment_id}:delete",
        )


def _summarise_comment_diff(comment: Comment, diff: dict) -> str:
    """Human-readable label for the history popover. Max ~80 chars."""
    fields = ", ".join(sorted(diff.keys()))
    return f"Edited comment — {fields}"[:80]
