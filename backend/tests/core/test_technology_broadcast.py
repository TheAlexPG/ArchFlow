"""Smoke test the technology.* broadcast wiring.

Confirms the event names + payload shapes the frontend is about to
subscribe to actually pass through the workspace-room plumbing.
Full integration via HTTP lives in tests/api/test_technologies.py
and runs once the migrations are applied to the dev DB.
"""
import json
import uuid
from dataclasses import dataclass, field

from app.realtime.manager import publish_workspace_event


@dataclass
class _FakeWebSocket:
    sent: list[str] = field(default_factory=list)

    async def send_text(self, msg: str) -> None:
        self.sent.append(msg)


async def test_technology_created_event_reaches_workspace_room():
    from app.realtime.manager import manager

    await manager.start()
    try:
        ws = _FakeWebSocket()
        workspace_id = uuid.uuid4()
        await manager.join(
            f"workspace:{workspace_id}", ws, user_id=None, user_name="tester"
        )

        technology_body = {
            "id": str(uuid.uuid4()),
            "workspace_id": str(workspace_id),
            "slug": "my-custom",
            "name": "My Custom",
            "iconify_name": "logos:python",
            "category": "tool",
            "color": None,
            "aliases": None,
        }
        await publish_workspace_event(
            workspace_id, "technology.created", {"technology": technology_body}
        )

        assert ws.sent, "subscriber should receive the technology.created frame"
        body = json.loads(ws.sent[0])
        assert body["type"] == "technology.created"
        assert body["technology"]["slug"] == "my-custom"
    finally:
        manager._local.rooms.clear()


async def test_technology_deleted_uses_id_only_payload():
    from app.realtime.manager import manager

    await manager.start()
    try:
        ws = _FakeWebSocket()
        workspace_id = uuid.uuid4()
        tech_id = uuid.uuid4()
        await manager.join(
            f"workspace:{workspace_id}", ws, user_id=None, user_name="tester"
        )

        await publish_workspace_event(
            workspace_id, "technology.deleted", {"id": str(tech_id)}
        )

        assert ws.sent
        body = json.loads(ws.sent[0])
        assert body["type"] == "technology.deleted"
        assert body["id"] == str(tech_id)
        # Delete payload is intentionally slim — only the id.
        assert set(body.keys()) == {"type", "id"}
    finally:
        manager._local.rooms.clear()


async def test_technology_events_are_scoped_to_workspace_room():
    """A subscriber on a different workspace must not receive the event."""
    from app.realtime.manager import manager

    await manager.start()
    try:
        mine = _FakeWebSocket()
        theirs = _FakeWebSocket()
        my_ws = uuid.uuid4()
        their_ws = uuid.uuid4()

        await manager.join(f"workspace:{my_ws}", mine, user_id=None, user_name="me")
        await manager.join(
            f"workspace:{their_ws}", theirs, user_id=None, user_name="they"
        )

        await publish_workspace_event(
            my_ws, "technology.updated", {"technology": {"id": "x"}}
        )

        assert mine.sent
        assert not theirs.sent, "other workspace must not see this workspace's event"
    finally:
        manager._local.rooms.clear()
