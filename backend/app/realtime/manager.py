"""In-memory connection manager + Redis pub/sub fan-out for live updates.

Design:
    - Each open diagram (or draft fork) is a "room". Rooms are keyed by
      their diagram id; we speak JSON messages inside them.
    - Every process instance holds local WebSockets in `_rooms`. Sending
      an event to a room does two things:
        1. Broadcast to every local socket in that room.
        2. Publish to Redis `ws:{room_id}` so other instances pick it up.
    - One background task per instance subscribes to `ws:*` (pattern) and
      re-broadcasts incoming messages to their local rooms.
    - Cursor frames are fire-and-forget — never persisted. Object/
      connection/diagram events are just Redis echoes of the REST
      endpoints and the receiver can refetch authoritatively.

Why Redis instead of direct socket-to-socket:
    Even with one instance today, the pub/sub layer means day-one scale-
    out ships (behind gunicorn -w N, or multiple containers) without a
    second rewrite.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

REDIS_CHANNEL_PREFIX = "ws:"


@dataclass(eq=False)
class RoomMember:
    """Identity-compared so two members with the same user_id still occupy
    their own slot in the room's set (tab-in-tab multi-session)."""

    websocket: WebSocket
    user_id: uuid.UUID | None
    # User-facing display. Keeps the cursor label off of the user id which
    # the front-end shouldn't need to resolve separately.
    user_name: str = ""


@dataclass
class _LocalRooms:
    rooms: dict[str, set[RoomMember]] = field(default_factory=dict)


class ConnectionManager:
    def __init__(self) -> None:
        self._local = _LocalRooms()
        self._subscriber_task: asyncio.Task | None = None
        # Lets the subscriber skip re-broadcasting messages this same
        # instance just published to Redis (otherwise we'd double-deliver
        # to every local socket, including the one that sent a cursor).
        self._instance_id = str(uuid.uuid4())

    # ── lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Spin up the Redis subscriber if it isn't running yet."""
        if self._subscriber_task is None or self._subscriber_task.done():
            self._subscriber_task = asyncio.create_task(self._subscribe_loop())

    async def stop(self) -> None:
        task = self._subscriber_task
        self._subscriber_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ── room membership ────────────────────────────────────────────

    async def join(
        self,
        room_id: str,
        websocket: WebSocket,
        user_id: uuid.UUID | None,
        user_name: str = "",
    ) -> RoomMember:
        member = RoomMember(websocket=websocket, user_id=user_id, user_name=user_name)
        self._local.rooms.setdefault(room_id, set()).add(member)
        await self.start()
        return member

    def leave(self, room_id: str, member: RoomMember) -> None:
        members = self._local.rooms.get(room_id)
        if members is None:
            return
        members.discard(member)
        if not members:
            self._local.rooms.pop(room_id, None)

    def room_users(self, room_id: str) -> list[dict[str, Any]]:
        """Snapshot of who's in the room right now, for presence.

        Useful when a new user joins so we can send them the current
        roster in a single message rather than making them wait for
        someone to move their cursor."""
        return [
            {"user_id": str(m.user_id) if m.user_id else None, "user_name": m.user_name}
            for m in self._local.rooms.get(room_id, set())
        ]

    # ── publish + fan-out ──────────────────────────────────────────

    async def publish(
        self, room_id: str, event: dict[str, Any], skip_self: RoomMember | None = None
    ) -> None:
        """Send an event to every member of `room_id` across every
        instance. `skip_self` lets the sender avoid echoing its own
        cursor back to itself.
        """
        await self._broadcast_local(room_id, event, skip=skip_self)
        # Stamp with our instance id so our own subscriber ignores the
        # echo and doesn't double-deliver to local sockets.
        redis_payload = dict(event)
        redis_payload["_origin"] = self._instance_id
        try:
            await redis_client.publish(
                REDIS_CHANNEL_PREFIX + room_id,
                json.dumps(redis_payload, default=str),
            )
        except Exception:
            logger.exception("failed to publish ws event to redis")

    async def _broadcast_local(
        self,
        room_id: str,
        event: dict[str, Any],
        skip: RoomMember | None = None,
    ) -> None:
        members = list(self._local.rooms.get(room_id, set()))
        if not members:
            return
        payload = json.dumps(event, default=str)
        for m in members:
            if m is skip:
                continue
            try:
                await m.websocket.send_text(payload)
            except Exception:
                logger.debug("dropping ws member on send failure", exc_info=True)
                self.leave(room_id, m)

    async def _subscribe_loop(self) -> None:
        """One task per process. Re-broadcasts Redis messages locally.

        Uses pattern subscribe so we don't have to re-subscribe every
        time a new room opens.
        """
        pubsub = redis_client.pubsub()
        await pubsub.psubscribe(REDIS_CHANNEL_PREFIX + "*")
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "pmessage":
                    continue
                channel = msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                room_id = channel[len(REDIS_CHANNEL_PREFIX):]
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    event = json.loads(data)
                except Exception:
                    logger.warning("unparseable redis ws payload on %s", channel)
                    continue
                if event.pop("_origin", None) == self._instance_id:
                    # Our own publish echoing back — local sockets already
                    # saw this frame via _broadcast_local.
                    continue
                await self._broadcast_local(room_id, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ws subscribe loop crashed")
        finally:
            try:
                await pubsub.punsubscribe(REDIS_CHANNEL_PREFIX + "*")
                await pubsub.aclose()
            except Exception:
                pass


# Singleton — shared by the WS endpoint and any service that wants to
# publish events.
manager = ConnectionManager()


async def publish_workspace_event(
    workspace_id: uuid.UUID | str, event_type: str, payload: dict[str, Any]
) -> None:
    """Shortcut used by REST endpoints to push a live event into the
    workspace's rooms.

    For now every workspace is a single room. When we want per-diagram
    granularity, the caller passes diagram_id directly via `publish`.
    """
    room_id = f"workspace:{workspace_id}"
    await manager.publish(room_id, {"type": event_type, **payload})


def fire_and_forget_publish(
    workspace_id: uuid.UUID | str | None, event_type: str, payload: dict[str, Any]
) -> None:
    """Non-blocking wrapper for REST endpoints.

    `workspace_id=None` is silently dropped — used by code paths that
    don't know the workspace yet (legacy resources pre-workspace FK).
    """
    if workspace_id is None:
        return

    async def _go() -> None:
        try:
            await publish_workspace_event(workspace_id, event_type, payload)
        except Exception:
            logger.exception("ws publish failed for %s", event_type)

    asyncio.create_task(_go())


def fire_and_forget_publish_diagram(
    diagram_id: uuid.UUID | str | None, event_type: str, payload: dict[str, Any]
) -> None:
    """Publish to `diagram:{id}` — every client subscribed via
    useDiagramSocket picks it up, even if they're in a different
    workspace. Used for events scoped to a single open diagram."""
    if diagram_id is None:
        return
    room_id = f"diagram:{diagram_id}"

    async def _go() -> None:
        try:
            await manager.publish(room_id, {"type": event_type, **payload})
        except Exception:
            logger.exception("ws publish failed for %s", event_type)

    asyncio.create_task(_go())
