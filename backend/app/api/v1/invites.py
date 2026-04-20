"""Invite acceptance endpoint — not workspace-scoped because the caller
discovers the workspace via the invite token, not via the URL.

Flow:
    1. Admin invites bob@example.com via POST /workspaces/{id}/invites
       → returns a token.
    2. Bob registers or signs in with that email.
    3. Bob hits POST /invites/accept with the token.
    4. Backend verifies token.email == bob.email, creates membership,
       auto-joins pre-assigned teams, marks invite accepted.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import member_service

router = APIRouter(prefix="/invites", tags=["invites"])


class AcceptInviteRequest(BaseModel):
    token: str


class AcceptInviteResponse(BaseModel):
    workspace_id: str
    role: str


@router.post("/accept", response_model=AcceptInviteResponse)
async def accept_invite(
    payload: AcceptInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member = await member_service.accept_invite(db, payload.token, current_user)
    if member is None:
        raise HTTPException(
            400,
            "Invalid invite — either already used, revoked, or the email "
            "on the invite does not match your account",
        )
    return AcceptInviteResponse(
        workspace_id=str(member.workspace_id), role=member.role.value
    )
