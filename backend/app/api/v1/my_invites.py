"""Invites targeted at the currently-signed-in user.

The admin side (listed at /workspaces/{id}/invites) issues pending invites
by email. We surface them here so the invitee can see, accept, or decline
them in-app — independent of the token email flow.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import member_service

router = APIRouter(prefix="/me/invites", tags=["my-invites"])


class MyInviteResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    role: str
    invited_at: str


class AcceptResponse(BaseModel):
    workspace_id: UUID
    role: str


@router.get("", response_model=list[MyInviteResponse])
async def list_my_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await member_service.list_pending_for_email(db, current_user.email)
    return [
        MyInviteResponse(
            id=inv.id,
            workspace_id=ws.id,
            workspace_name=ws.name,
            role=inv.role.value,
            invited_at=inv.created_at.isoformat(),
        )
        for inv, ws in rows
    ]


@router.post("/{invite_id}/accept", response_model=AcceptResponse)
async def accept_my_invite(
    invite_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member = await member_service.accept_invite_by_id(db, invite_id, current_user)
    if member is None:
        raise HTTPException(
            400,
            "Invite not found, already handled, or addressed to a different email",
        )
    return AcceptResponse(
        workspace_id=member.workspace_id, role=member.role.value
    )


@router.post("/{invite_id}/decline", status_code=204)
async def decline_my_invite(
    invite_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await member_service.decline_invite_by_id(db, invite_id, current_user)
    if not ok:
        raise HTTPException(
            400,
            "Invite not found, already handled, or addressed to a different email",
        )
