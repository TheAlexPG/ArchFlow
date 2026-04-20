"""WebSocket endpoint for live collaboration.

Flow:
    1. Client opens `ws://.../api/v1/ws/diagrams/{diagram_id}?token=<jwt>`
    2. Server validates JWT, joins the diagram's room, sends the current
       presence roster ({type: 'presence.init', users: [...]}).
    3. Server also broadcasts {type: 'presence.join', user} to everyone
       else in the room.
    4. Client messages:
         {type: 'cursor', x, y}        → fanned out to room
         {type: 'selection', ids: [..]} → fanned out
         {type: 'ping'}                 → server replies {type: 'pong'}
    5. On disconnect, server broadcasts {type: 'presence.leave', user}.

JWT auth via query param (the header-based auth browsers don't support
on WebSocket). Same decode_token + type check as REST.
"""
import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.database import async_session
from app.core.security import decode_token
from app.models.user import User
from app.realtime.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["ws"])


async def _authenticate(token: str) -> User | None:
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    async with async_session() as s:
        result = await s.execute(select(User).where(User.id == payload["sub"]))
        return result.scalar_one_or_none()


@router.websocket("/diagrams/{diagram_id}")
async def diagram_socket(
    websocket: WebSocket,
    diagram_id: str,
    token: str = Query(..., description="Access JWT"),
):
    user = await _authenticate(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    room_id = f"diagram:{diagram_id}"
    member = await manager.join(
        room_id=room_id,
        websocket=websocket,
        user_id=user.id,
        user_name=user.name,
    )

    try:
        # Tell the newcomer who else is already here.
        await websocket.send_text(
            json.dumps(
                {"type": "presence.init", "users": manager.room_users(room_id)}
            )
        )
        # Tell everyone else a new user just showed up.
        await manager.publish(
            room_id,
            {
                "type": "presence.join",
                "user": {"user_id": str(user.id), "user_name": user.name},
            },
            skip_self=member,
        )

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if kind in ("cursor", "selection"):
                # Stamp the author so receivers can tell which cursor to
                # move without having to track their own outbound frames.
                msg["user_id"] = str(user.id)
                msg["user_name"] = user.name
                await manager.publish(room_id, msg, skip_self=member)
                continue
            # Unknown client-to-server messages are ignored silently —
            # good defaults for forward compat.
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws handler crashed")
    finally:
        manager.leave(room_id, member)
        try:
            await manager.publish(
                room_id,
                {
                    "type": "presence.leave",
                    "user": {"user_id": str(user.id), "user_name": user.name},
                },
            )
        except Exception:
            pass


@router.websocket("/workspace/{workspace_id}")
async def workspace_socket(
    websocket: WebSocket,
    workspace_id: str,
    token: str = Query(..., description="Access JWT"),
):
    """Workspace-level firehose — receives object/connection/diagram
    change events so the UI can refetch without waiting for explicit
    query invalidations."""
    user = await _authenticate(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    room_id = f"workspace:{workspace_id}"
    try:
        uuid.UUID(workspace_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    member = await manager.join(
        room_id=room_id,
        websocket=websocket,
        user_id=user.id,
        user_name=user.name,
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("workspace ws crashed")
    finally:
        manager.leave(room_id, member)
