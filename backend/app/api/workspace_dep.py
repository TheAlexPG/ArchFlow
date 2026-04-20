from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services import workspace_service


async def get_current_workspace(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """Resolve the workspace the request targets.

    Precedence:
    1. `X-Workspace-ID` header if the caller provided one
    2. The caller's oldest (first-created) workspace — their "personal" one

    Always verifies that the caller is a member of the resolved workspace.
    """
    from sqlalchemy import select

    header = request.headers.get("X-Workspace-ID")
    if header:
        try:
            workspace_id = UUID(header)
        except ValueError as e:
            raise HTTPException(400, "Invalid X-Workspace-ID") from e
        membership = await workspace_service.get_user_membership(
            db, current_user.id, workspace_id
        )
        if membership is None:
            raise HTTPException(403, "Not a member of this workspace")
        ws = (
            await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if ws is None:
            raise HTTPException(404, "Workspace not found")
        return ws

    ws = await workspace_service.get_default_workspace_for_user(db, current_user.id)
    if ws is None:
        raise HTTPException(403, "No workspace assigned to this user")
    return ws
