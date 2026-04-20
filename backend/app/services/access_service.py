"""Per-diagram access control via teams.

Visibility rule (one of these must be true):
- Caller is workspace admin or owner → can see everything.
- The diagram has NO grants attached at all → fall back to workspace-wide
  visibility (every workspace member sees it).
- The diagram has at least one grant, and the caller is a member of one of
  those teams.

Mutation (create/update/delete) requires `write` or `admin` grant, OR the
caller being a workspace admin/owner. Workspace editors without explicit team
access to a restricted diagram can't mutate it.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import has_role
from app.models.diagram import Diagram
from app.models.team import AccessLevel, DiagramAccess, TeamMember, Team
from app.models.workspace import Role


async def list_diagram_grants(
    db: AsyncSession, diagram_id: uuid.UUID
) -> list[DiagramAccess]:
    result = await db.execute(
        select(DiagramAccess).where(DiagramAccess.diagram_id == diagram_id)
    )
    return list(result.scalars().all())


async def grant_team_access(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    team_id: uuid.UUID,
    level: AccessLevel,
) -> DiagramAccess:
    existing = await db.execute(
        select(DiagramAccess).where(
            DiagramAccess.diagram_id == diagram_id,
            DiagramAccess.team_id == team_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        row.access_level = level
    else:
        row = DiagramAccess(
            diagram_id=diagram_id, team_id=team_id, access_level=level
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def revoke_team_access(
    db: AsyncSession, diagram_id: uuid.UUID, team_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(DiagramAccess).where(
            DiagramAccess.diagram_id == diagram_id,
            DiagramAccess.team_id == team_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def can_read_diagram(
    db: AsyncSession, user_id: uuid.UUID, diagram: Diagram, role: Role
) -> bool:
    if has_role(role, Role.ADMIN):
        return True
    grants = await list_diagram_grants(db, diagram.id)
    if not grants:
        return True  # no restriction yet — workspace-wide visibility

    # Caller must be in at least one granted team.
    team_ids = {g.team_id for g in grants}
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == user_id, TeamMember.team_id.in_(team_ids)
        )
    )
    return result.scalar_one_or_none() is not None


async def can_write_diagram(
    db: AsyncSession, user_id: uuid.UUID, diagram: Diagram, role: Role
) -> bool:
    if has_role(role, Role.ADMIN):
        return True
    if not has_role(role, Role.EDITOR):
        return False
    grants = await list_diagram_grants(db, diagram.id)
    if not grants:
        return True
    # Need write or admin on a team we belong to.
    result = await db.execute(
        select(DiagramAccess, TeamMember)
        .join(TeamMember, TeamMember.team_id == DiagramAccess.team_id)
        .where(
            DiagramAccess.diagram_id == diagram.id,
            TeamMember.user_id == user_id,
            DiagramAccess.access_level.in_(
                [AccessLevel.WRITE.value, AccessLevel.ADMIN.value]
            ),
        )
    )
    return result.first() is not None


async def filter_visible_diagram_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    role: Role,
) -> set[uuid.UUID] | None:
    """Return the set of diagram ids in `workspace_id` that `user_id` can read.

    Returns `None` to signal "no restriction at all" (admin+ in the whole
    workspace); the caller should treat `None` as "all diagrams visible".
    """
    if has_role(role, Role.ADMIN):
        return None

    # Find every diagram that either (a) has no grants or (b) has a grant
    # shared with one of the user's teams.
    all_diagrams = await db.execute(
        select(Diagram.id).where(Diagram.workspace_id == workspace_id)
    )
    all_ids = {d for (d,) in all_diagrams.all()}

    restricted = await db.execute(
        select(DiagramAccess.diagram_id).distinct().where(
            DiagramAccess.diagram_id.in_(all_ids)
        )
    )
    restricted_ids = {d for (d,) in restricted.all()}
    open_ids = all_ids - restricted_ids

    if not restricted_ids:
        return open_ids

    accessible_restricted = await db.execute(
        select(DiagramAccess.diagram_id).distinct()
        .join(TeamMember, TeamMember.team_id == DiagramAccess.team_id)
        .where(
            DiagramAccess.diagram_id.in_(restricted_ids),
            TeamMember.user_id == user_id,
        )
    )
    accessible_ids = {d for (d,) in accessible_restricted.all()}
    return open_ids | accessible_ids
