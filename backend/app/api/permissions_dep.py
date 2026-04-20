from collections.abc import Callable
from typing import Awaitable

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.workspace_dep import get_current_workspace
from app.core.database import get_db
from app.core.permissions import has_role
from app.models.user import User
from app.models.workspace import Role, Workspace
from app.services import workspace_service


async def get_workspace_role(
    workspace: Workspace = Depends(get_current_workspace),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Role:
    membership = await workspace_service.get_user_membership(
        db, current_user.id, workspace.id
    )
    if membership is None:
        raise HTTPException(403, "Not a member of this workspace")
    return membership.role


def require_role(minimum: Role) -> Callable[..., Awaitable[Role]]:
    """Returns a FastAPI dependency that enforces `minimum` or higher.

    Use as `Depends(require_role(Role.ADMIN))` on endpoints that mutate
    workspace-level state (member changes, team CRUD, etc.).
    """

    async def _dep(role: Role = Depends(get_workspace_role)) -> Role:
        if not has_role(role, minimum):
            raise HTTPException(
                403, f"Requires {minimum.value} or higher (you are {role.value})"
            )
        return role

    return _dep
