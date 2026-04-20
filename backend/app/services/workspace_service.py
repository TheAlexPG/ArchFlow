import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import Organization, Role, Workspace, WorkspaceMember


async def create_personal_workspace(
    db: AsyncSession, user: User
) -> tuple[Organization, Workspace, WorkspaceMember]:
    """Provision a personal org + workspace + owner membership for a new user."""
    org = Organization(
        name=f"{user.name}'s personal org", slug=f"personal-{user.id}"
    )
    db.add(org)
    await db.flush()

    workspace = Workspace(org_id=org.id, name="Personal", slug="personal")
    db.add(workspace)
    await db.flush()

    membership = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role=Role.OWNER
    )
    db.add(membership)
    await db.flush()
    return org, workspace, membership


async def list_user_workspaces(
    db: AsyncSession, user_id: uuid.UUID
) -> list[Workspace]:
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at)
    )
    return list(result.scalars().all())


async def get_user_membership(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> WorkspaceMember | None:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def get_default_workspace_for_user(
    db: AsyncSession, user_id: uuid.UUID
) -> Workspace | None:
    """Return the caller's first (oldest) workspace. Used when no explicit
    X-Workspace-ID header is set on the request."""
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()
