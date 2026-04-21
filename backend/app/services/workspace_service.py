import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import Organization, Role, Workspace, WorkspaceMember


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    return base[:60]


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


async def create_workspace(
    db: AsyncSession, user: User, name: str
) -> tuple[Workspace, WorkspaceMember]:
    """Create a new workspace under the user's existing personal org and
    make them its owner. Slug is derived from the name; a counter is
    appended if it collides within the org."""
    clean = name.strip()
    if not clean:
        raise ValueError("Name is required")

    # Re-use the user's first org — multi-org is out of scope right now.
    member_q = await db.execute(
        select(Workspace.org_id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at)
        .limit(1)
    )
    org_id = member_q.scalar_one_or_none()
    if org_id is None:
        # User has no workspaces (edge case — normally provisioned at
        # registration). Bootstrap a personal org so they aren't stuck.
        org = Organization(
            name=f"{user.name}'s personal org", slug=f"personal-{user.id}"
        )
        db.add(org)
        await db.flush()
        org_id = org.id

    base = _slugify(clean)
    slug = base
    counter = 2
    while True:
        existing = await db.execute(
            select(Workspace.id).where(
                Workspace.org_id == org_id, Workspace.slug == slug
            )
        )
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base}-{counter}"
        counter += 1

    ws = Workspace(org_id=org_id, name=clean, slug=slug)
    db.add(ws)
    await db.flush()
    membership = WorkspaceMember(
        workspace_id=ws.id, user_id=user.id, role=Role.OWNER
    )
    db.add(membership)
    await db.commit()
    await db.refresh(ws)
    await db.refresh(membership)
    return ws, membership


async def rename_workspace(
    db: AsyncSession, workspace_id: uuid.UUID, name: str
) -> Workspace:
    clean = name.strip()
    if not clean:
        raise ValueError("Name is required")
    ws = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if ws is None:
        raise ValueError("Workspace not found")
    ws.name = clean
    await db.commit()
    await db.refresh(ws)
    return ws


class WorkspaceHasContentError(ValueError):
    """Raised when deletion is blocked because the workspace still has
    diagrams or is the caller's last one."""


async def delete_workspace(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Delete an empty workspace. Safety rails: the caller must have at
    least one other workspace (so we don't strand them), and the
    workspace must have no diagrams (prevents accidental bulk loss).
    """
    # How many workspaces does the caller own/belong to?
    count_q = await db.execute(
        select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.user_id == user_id
        )
    )
    if (count_q.scalar_one() or 0) <= 1:
        raise WorkspaceHasContentError(
            "Can't delete your last workspace — create another first"
        )

    from app.models.diagram import Diagram

    diagrams_q = await db.execute(
        select(func.count(Diagram.id)).where(Diagram.workspace_id == workspace_id)
    )
    if (diagrams_q.scalar_one() or 0) > 0:
        raise WorkspaceHasContentError(
            "Workspace still has diagrams — remove them before deleting"
        )

    ws = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if ws is None:
        raise ValueError("Workspace not found")
    await db.delete(ws)
    await db.commit()


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
