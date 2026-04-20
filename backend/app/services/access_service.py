"""Per-diagram access control via teams or direct user grants.

Visibility rule (one must be true):
- Caller is workspace admin or owner → sees everything.
- Diagram has NO grants → workspace-wide visibility.
- Diagram has at least one grant, AND the caller is granted directly OR
  is a member of a granted team.

Mutation (create/update/delete) requires `write` or `admin` grant (direct or
via team), OR the caller being a workspace admin/owner.
"""
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import has_role
from app.models.diagram import Diagram
from app.models.team import AccessLevel, DiagramAccess, TeamMember
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


async def grant_user_access(
    db: AsyncSession,
    diagram_id: uuid.UUID,
    user_id: uuid.UUID,
    level: AccessLevel,
) -> DiagramAccess:
    existing = await db.execute(
        select(DiagramAccess).where(
            DiagramAccess.diagram_id == diagram_id,
            DiagramAccess.user_id == user_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        row.access_level = level
    else:
        row = DiagramAccess(
            diagram_id=diagram_id, user_id=user_id, access_level=level
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def revoke_user_access(
    db: AsyncSession, diagram_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(DiagramAccess).where(
            DiagramAccess.diagram_id == diagram_id,
            DiagramAccess.user_id == user_id,
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
        return True  # no restriction → workspace-wide visibility

    # Direct user grant?
    if any(g.user_id == user_id for g in grants):
        return True

    # Via a team?
    team_ids = {g.team_id for g in grants if g.team_id is not None}
    if not team_ids:
        return False
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

    write_levels = [AccessLevel.WRITE.value, AccessLevel.ADMIN.value]

    # Direct write grant?
    if any(
        g.user_id == user_id and g.access_level.value in write_levels for g in grants
    ):
        return True

    # Write via a team we're in?
    result = await db.execute(
        select(DiagramAccess)
        .join(TeamMember, TeamMember.team_id == DiagramAccess.team_id)
        .where(
            DiagramAccess.diagram_id == diagram.id,
            TeamMember.user_id == user_id,
            DiagramAccess.access_level.in_(write_levels),
        )
    )
    return result.first() is not None


async def filter_visible_diagram_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    role: Role,
) -> set[uuid.UUID] | None:
    """Diagram ids in `workspace_id` that `user_id` can read.

    Returns `None` to signal "no restriction at all" (admin+); the caller
    should treat that as "all diagrams visible".
    """
    if has_role(role, Role.ADMIN):
        return None

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

    # Diagrams where the caller has direct or team grant.
    accessible = await db.execute(
        select(DiagramAccess.diagram_id).distinct()
        .outerjoin(TeamMember, TeamMember.team_id == DiagramAccess.team_id)
        .where(
            DiagramAccess.diagram_id.in_(restricted_ids),
            or_(
                DiagramAccess.user_id == user_id,
                TeamMember.user_id == user_id,
            ),
        )
    )
    accessible_ids = {d for (d,) in accessible.all()}
    return open_ids | accessible_ids
