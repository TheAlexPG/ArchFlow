import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team, TeamMember
from app.models.user import User
from app.models.workspace import WorkspaceMember


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "team"


async def create_team(
    db: AsyncSession, workspace_id: uuid.UUID, name: str, description: str | None
) -> Team:
    team = Team(
        workspace_id=workspace_id,
        name=name,
        slug=_slugify(name),
        description=description,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


async def list_teams(db: AsyncSession, workspace_id: uuid.UUID) -> list[Team]:
    result = await db.execute(
        select(Team).where(Team.workspace_id == workspace_id).order_by(Team.name)
    )
    return list(result.scalars().all())


async def get_team(
    db: AsyncSession, workspace_id: uuid.UUID, team_id: uuid.UUID
) -> Team | None:
    result = await db.execute(
        select(Team).where(Team.id == team_id, Team.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def delete_team(db: AsyncSession, team: Team) -> None:
    await db.delete(team)
    await db.commit()


async def list_team_members(
    db: AsyncSession, team_id: uuid.UUID
) -> list[tuple[TeamMember, User]]:
    result = await db.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(User.name)
    )
    return [(tm, u) for tm, u in result.all()]


async def add_team_member(
    db: AsyncSession, team: Team, user_id: uuid.UUID
) -> TeamMember:
    # Enforce that only workspace members can be added to a team — this keeps
    # team membership from outgrowing workspace access (and avoiding weird
    # cross-workspace team situations later).
    workspace_member = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == team.workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
    if workspace_member.scalar_one_or_none() is None:
        raise ValueError("User is not a member of this team's workspace")

    exists = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team.id, TeamMember.user_id == user_id
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise ValueError("User already in this team")

    row = TeamMember(team_id=team.id, user_id=user_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def remove_team_member(
    db: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_user_team_ids(
    db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[uuid.UUID]:
    """Team ids this user belongs to within the given workspace."""
    result = await db.execute(
        select(TeamMember.team_id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(Team.workspace_id == workspace_id, TeamMember.user_id == user_id)
    )
    return [tid for (tid,) in result.all()]
