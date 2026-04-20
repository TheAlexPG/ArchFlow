import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite import WorkspaceInvite
from app.models.user import User
from app.models.workspace import Role, WorkspaceMember


class LastOwnerError(ValueError):
    """Raised when an operation would demote or remove the last owner."""


async def list_members(
    db: AsyncSession, workspace_id: uuid.UUID
) -> list[tuple[WorkspaceMember, User]]:
    result = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.name)
    )
    return [(m, u) for m, u in result.all()]


async def _count_owners(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == Role.OWNER,
        )
    )
    return len(list(result.scalars().all()))


async def update_member_role(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, new_role: Role
) -> WorkspaceMember:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise ValueError("Not a member of this workspace")

    if member.role == Role.OWNER and new_role != Role.OWNER:
        if await _count_owners(db, workspace_id) <= 1:
            raise LastOwnerError("Can't demote the last owner")

    member.role = new_role
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise ValueError("Not a member of this workspace")

    if member.role == Role.OWNER and await _count_owners(db, workspace_id) <= 1:
        raise LastOwnerError("Can't remove the last owner")

    await db.delete(member)
    await db.commit()


async def invite_user(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    email: str,
    role: Role,
    invited_by_user_id: uuid.UUID | None,
) -> tuple[WorkspaceInvite | None, WorkspaceMember | None]:
    """If the email is already a registered user, add them as a member
    immediately. Otherwise persist a pending invite with a unique token —
    the user picks up the invite after they register.

    Returns either (invite, None) or (None, member).
    """
    user_q = await db.execute(select(User).where(User.email == email))
    existing_user = user_q.scalar_one_or_none()
    if existing_user is not None:
        member_q = await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == existing_user.id,
            )
        )
        if member_q.scalar_one_or_none():
            raise ValueError("User is already a member of this workspace")
        member = WorkspaceMember(
            workspace_id=workspace_id, user_id=existing_user.id, role=role
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        return None, member

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        invited_by_user_id=invited_by_user_id,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite, None


async def accept_invite(
    db: AsyncSession, token: str, user: User
) -> WorkspaceMember | None:
    result = await db.execute(
        select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    )
    invite = result.scalar_one_or_none()
    if invite is None or invite.accepted_at is not None or invite.revoked_at is not None:
        return None
    if invite.email != user.email:
        return None
    from datetime import UTC, datetime

    invite.accepted_at = datetime.now(UTC)
    member = WorkspaceMember(
        workspace_id=invite.workspace_id, user_id=user.id, role=invite.role
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def list_invites(
    db: AsyncSession, workspace_id: uuid.UUID
) -> list[WorkspaceInvite]:
    result = await db.execute(
        select(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.revoked_at.is_(None),
        )
        .order_by(WorkspaceInvite.created_at.desc())
    )
    return list(result.scalars().all())
