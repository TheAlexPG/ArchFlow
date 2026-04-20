"""Realtime plumbing tests.

Starlette's sync TestClient and asyncpg don't cooperate (task-across-loop
errors), and httpx.AsyncClient doesn't speak WebSocket. So these tests
exercise the plumbing directly:

  - ConnectionManager.join/leave/publish with a fake WebSocket
  - Redis pub/sub round-trip between two manager instances sharing Redis
  - publish_workspace_event dispatch shape

End-to-end `ws://` smoke is deferred to a browser/e2e harness.
"""
import asyncio
import json
import uuid
from dataclasses import dataclass, field

import pytest

from app.realtime.manager import ConnectionManager, publish_workspace_event


@dataclass
class FakeWebSocket:
    """Captures what the manager tries to send. No network."""

    sent: list[str] = field(default_factory=list)

    async def send_text(self, msg: str) -> None:
        self.sent.append(msg)


async def test_local_broadcast_skips_sender():
    mgr = ConnectionManager()
    try:
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        m1 = await mgr.join("diagram:r1", ws1, user_id=None, user_name="A")
        await mgr.join("diagram:r1", ws2, user_id=None, user_name="B")

        await mgr.publish("diagram:r1", {"type": "cursor", "x": 5}, skip_self=m1)

        assert ws1.sent == [], "sender should not receive its own frame"
        assert len(ws2.sent) == 1
        body = json.loads(ws2.sent[0])
        assert body["type"] == "cursor"
        assert body["x"] == 5
    finally:
        await mgr.stop()


async def test_leave_drops_socket():
    mgr = ConnectionManager()
    try:
        ws = FakeWebSocket()
        m = await mgr.join("diagram:r2", ws, user_id=None, user_name="A")
        mgr.leave("diagram:r2", m)

        # After leave the room is empty — publish is a no-op locally.
        await mgr.publish("diagram:r2", {"type": "cursor"})
        assert ws.sent == []

        assert mgr.room_users("diagram:r2") == []
    finally:
        await mgr.stop()


async def test_room_users_reflects_membership():
    mgr = ConnectionManager()
    try:
        u1 = uuid.uuid4()
        u2 = uuid.uuid4()
        await mgr.join("diagram:r3", FakeWebSocket(), user_id=u1, user_name="A")
        await mgr.join("diagram:r3", FakeWebSocket(), user_id=u2, user_name="B")

        roster = mgr.room_users("diagram:r3")
        assert {r["user_name"] for r in roster} == {"A", "B"}
    finally:
        await mgr.stop()


async def test_cross_instance_fanout_via_redis():
    """Two managers sharing Redis — a publish from one reaches sockets
    on the other. Proves the Redis subscriber re-broadcasts locally."""
    mgr_a = ConnectionManager()
    mgr_b = ConnectionManager()
    try:
        ws_b = FakeWebSocket()
        room_id = f"diagram:{uuid.uuid4()}"
        await mgr_b.join(room_id, ws_b, user_id=None, user_name="B")

        # Give mgr_b's subscriber a tick to actually psubscribe.
        await asyncio.sleep(0.05)

        # Publish from mgr_a (no local subscribers) — Redis carries it.
        await mgr_a.publish(room_id, {"type": "object.updated", "id": "x"})

        # Wait for Redis round-trip.
        for _ in range(20):
            if ws_b.sent:
                break
            await asyncio.sleep(0.05)

        assert ws_b.sent, "mgr_b should receive the event via Redis"
        body = json.loads(ws_b.sent[0])
        assert body["type"] == "object.updated"
        assert body["id"] == "x"
    finally:
        await mgr_a.stop()
        await mgr_b.stop()


async def test_publish_workspace_event_targets_workspace_room():
    """publish_workspace_event uses `workspace:{id}` as the room key so
    REST endpoints and the workspace WebSocket agree on the channel."""
    from app.realtime.manager import manager  # shared singleton

    await manager.start()
    try:
        ws = FakeWebSocket()
        ws_id = uuid.uuid4()
        await manager.join(
            f"workspace:{ws_id}", ws, user_id=None, user_name="tester"
        )

        await publish_workspace_event(ws_id, "object.deleted", {"id": "abc"})

        assert ws.sent, "workspace subscriber should receive the event"
        body = json.loads(ws.sent[0])
        assert body["type"] == "object.deleted"
        assert body["id"] == "abc"
    finally:
        # Don't stop the module singleton — other tests depend on it being
        # available. Just clean room state.
        manager._local.rooms.clear()
