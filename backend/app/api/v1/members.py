from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.permissions_dep import require_role
from app.core.database import get_db
from app.models.user import User
from app.models.workspace import Role
from app.services import member_service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workspace-members"])


class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    name: str
    role: str


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: Role
    # Teams to auto-add the user to on acceptance. Ignored entries (wrong
    # workspace, deleted team) are silently skipped.
    team_ids: list[UUID] = []


class InviteResponse(BaseModel):
    id: UUID
    email: str
    role: str
    token: str
    team_ids: list[UUID]


class AcceptInviteRequest(BaseModel):
    token: str


class RoleUpdateRequest(BaseModel):
    role: Role


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    workspace_id: UUID,
    _: Role = Depends(require_role(Role.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    rows = await member_service.list_members(db, workspace_id)
    return [
        MemberResponse(
            user_id=user.id, email=user.email, name=user.name, role=member.role.value
        )
        for member, user in rows
    ]


@router.post("/invites", status_code=201)
async def invite_member(
    workspace_id: UUID,
    payload: InviteCreateRequest,
    current_user: User = Depends(get_current_user),
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        invite = await member_service.invite_user(
            db,
            workspace_id,
            payload.email,
            payload.role,
            current_user.id,
            team_ids=payload.team_ids,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "type": "invite_created",
        "invite": InviteResponse(
            id=invite.id,
            email=invite.email,
            role=invite.role.value,
            token=invite.token,
            team_ids=list(invite.team_ids),
        ).model_dump(mode="json"),
    }


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    workspace_id: UUID,
    invite_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    ok = await member_service.revoke_invite(db, workspace_id, invite_id)
    if not ok:
        raise HTTPException(404, "Invite not found or already accepted")


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    workspace_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    rows = await member_service.list_invites(db, workspace_id)
    return [
        InviteResponse(
            id=r.id,
            email=r.email,
            role=r.role.value,
            token=r.token,
            team_ids=list(r.team_ids),
        )
        for r in rows
    ]


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    payload: RoleUpdateRequest,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        member = await member_service.update_member_role(
            db, workspace_id, user_id, payload.role
        )
    except member_service.LastOwnerError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    from sqlalchemy import select

    from app.models.user import User as UserModel

    user = (
        await db.execute(select(UserModel).where(UserModel.id == user_id))
    ).scalar_one_or_none()
    assert user is not None
    return MemberResponse(
        user_id=user.id, email=user.email, name=user.name, role=member.role.value
    )


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    try:
        await member_service.remove_member(db, workspace_id, user_id)
    except member_service.LastOwnerError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
