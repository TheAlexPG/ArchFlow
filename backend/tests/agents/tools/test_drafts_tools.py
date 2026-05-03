"""Tests for app/agents/tools/drafts_tools.py

Six cases:
1. fork_diagram_to_draft — returns action + view_change payload.
2. fork_diagram_to_draft — default name (None) generates "Draft of <base_id>".
3. list_active_drafts — returns drafts for actor.
4. list_active_drafts — filtered by diagram_id.
5. discard_draft — preview when not confirmed.
6. discard_draft — confirmed deletes via draft_service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents.tools import drafts_tools  # noqa: F401 — import registers the tools
from app.agents.tools.base import ToolContext
from app.agents.tools.drafts_tools import (
    discard_draft,
    fork_diagram_to_draft,
    list_active_drafts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeActor:
    kind: str = "user"
    id: UUID = None  # type: ignore[assignment]
    scopes: tuple[str, ...] = ()
    role: Any = None


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


def _make_ctx(actor_id: UUID | None = None) -> ToolContext:
    ws = uuid4()
    actor_id = actor_id or uuid4()
    actor = FakeActor(kind="user", id=actor_id)
    return ToolContext(
        db=FakeSession(),
        actor=actor,
        workspace_id=ws,
        chat_context={"kind": "workspace", "id": ws},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode="full",
        active_draft_id=None,
        draft_target_diagram_id=None,
    )


def _make_draft(
    draft_id: UUID | None = None,
    name: str = "My Draft",
    author_id: UUID | None = None,
    diagrams: list[Any] | None = None,
) -> MagicMock:
    from app.models.draft import DraftStatus

    draft = MagicMock()
    draft.id = draft_id or uuid4()
    draft.name = name
    draft.author_id = author_id
    draft.status = DraftStatus.OPEN
    draft.diagrams = diagrams or []
    return draft


def _make_dd(
    source_diagram_id: UUID | None = None,
    forked_diagram_id: UUID | None = None,
) -> MagicMock:
    dd = MagicMock()
    dd.source_diagram_id = source_diagram_id or uuid4()
    dd.forked_diagram_id = forked_diagram_id or uuid4()
    return dd


# ---------------------------------------------------------------------------
# Test 1: fork_diagram_to_draft — returns action + view_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_diagram_to_draft_returns_action_and_view_change():
    base_diagram_id = uuid4()
    draft_id = uuid4()
    forked_diagram_id = uuid4()

    dd = _make_dd(
        source_diagram_id=base_diagram_id,
        forked_diagram_id=forked_diagram_id,
    )
    draft = _make_draft(draft_id=draft_id, name="Feature A")

    with patch(
        "app.services.draft_service.fork_existing_diagram",
        new=AsyncMock(return_value=(draft, dd)),
    ):
        args = fork_diagram_to_draft.input_schema(
            diagram_id=base_diagram_id,
            draft_name="Feature A",
        )
        ctx = _make_ctx()
        result = await fork_diagram_to_draft.handler(args, ctx)

    assert result["action"] == "diagram.draft_created"
    assert result["target_type"] == "diagram"
    assert result["target_id"] == draft_id
    assert result["base_diagram_id"] == base_diagram_id
    assert result["name"] == "Feature A"
    assert result["forked_diagram_id"] == forked_diagram_id

    vc = result["view_change"]
    assert vc["kind"] == "draft_created"
    assert vc["to"]["kind"] == "diagram"
    assert vc["to"]["id"] == str(base_diagram_id)
    assert vc["to"]["draft_id"] == str(draft_id)


# ---------------------------------------------------------------------------
# Test 2: fork_diagram_to_draft — default name generated from base_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_diagram_to_draft_default_name_generated():
    base_diagram_id = uuid4()
    draft_id = uuid4()
    forked_diagram_id = uuid4()

    dd = _make_dd(
        source_diagram_id=base_diagram_id,
        forked_diagram_id=forked_diagram_id,
    )
    # Simulate draft_service echoing back the auto-generated name.
    expected_name = f"Draft of {base_diagram_id}"
    draft = _make_draft(draft_id=draft_id, name=expected_name)

    with patch(
        "app.services.draft_service.fork_existing_diagram",
        new=AsyncMock(return_value=(draft, dd)),
    ) as mock_fork:
        args = fork_diagram_to_draft.input_schema(
            diagram_id=base_diagram_id,
            draft_name=None,  # no name supplied
        )
        ctx = _make_ctx()
        result = await fork_diagram_to_draft.handler(args, ctx)

    # Verify the service was called with the generated name.
    call_kwargs = mock_fork.call_args
    draft_data_arg = call_kwargs.kwargs.get("draft_data") or call_kwargs.args[2]
    assert draft_data_arg.name == expected_name

    # Result must still carry action + view_change.
    assert result["action"] == "diagram.draft_created"
    assert result["name"] == expected_name


# ---------------------------------------------------------------------------
# Test 3: list_active_drafts — returns all open drafts for actor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_drafts_returns_all_for_actor():
    actor_id = uuid4()

    dd1 = _make_dd()
    dd2 = _make_dd()
    draft1 = _make_draft(name="Draft 1", author_id=actor_id, diagrams=[dd1])
    draft2 = _make_draft(name="Draft 2", author_id=actor_id, diagrams=[dd2])

    with patch(
        "app.services.draft_service.list_drafts",
        new=AsyncMock(return_value=[draft1, draft2]),
    ):
        args = list_active_drafts.input_schema(diagram_id=None)
        ctx = _make_ctx(actor_id=actor_id)
        result = await list_active_drafts.handler(args, ctx)

    assert result["count"] == 2
    names = {d["name"] for d in result["drafts"]}
    assert names == {"Draft 1", "Draft 2"}


# ---------------------------------------------------------------------------
# Test 4: list_active_drafts — filtered by diagram_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_drafts_filtered_by_diagram_id():
    source_diagram_id = uuid4()
    forked_diagram_id = uuid4()

    rows = [
        {
            "draft_id": str(uuid4()),
            "draft_name": "Filtered Draft",
            "draft_status": "open",
            "source_diagram_id": str(source_diagram_id),
            "forked_diagram_id": str(forked_diagram_id),
        }
    ]

    with patch(
        "app.services.draft_service.get_drafts_for_diagram",
        new=AsyncMock(return_value=rows),
    ) as mock_get:
        args = list_active_drafts.input_schema(diagram_id=source_diagram_id)
        ctx = _make_ctx()
        result = await list_active_drafts.handler(args, ctx)

    mock_get.assert_awaited_once_with(ctx.db, source_diagram_id)
    assert result["count"] == 1
    draft_entry = result["drafts"][0]
    assert draft_entry["name"] == "Filtered Draft"
    assert draft_entry["base_diagram_id"] == str(source_diagram_id)
    assert draft_entry["forked_diagram_id"] == str(forked_diagram_id)


# ---------------------------------------------------------------------------
# Test 5: discard_draft — preview when not confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_draft_returns_preview_when_not_confirmed():
    draft_id = uuid4()
    dd1 = _make_dd()
    dd2 = _make_dd()
    draft = _make_draft(draft_id=draft_id, name="To Discard", diagrams=[dd1, dd2])

    with patch(
        "app.services.draft_service.get_draft",
        new=AsyncMock(return_value=draft),
    ):
        args = discard_draft.input_schema(draft_id=draft_id, confirmed=False)
        ctx = _make_ctx()
        result = await discard_draft.handler(args, ctx)

    assert result["status"] == "awaiting_confirmation"
    assert result["draft_id"] == str(draft_id)
    assert result["diagram_count"] == 2
    assert "confirmed=True" in result["preview"]
    assert "To Discard" in result["preview"]


# ---------------------------------------------------------------------------
# Test 6: discard_draft — confirmed deletes via draft_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_draft_confirmed_calls_service():
    from app.models.draft import DraftStatus

    draft_id = uuid4()
    draft = _make_draft(draft_id=draft_id, name="Bye Draft", diagrams=[])

    discarded_draft = _make_draft(draft_id=draft_id, name="Bye Draft")
    discarded_draft.status = DraftStatus.DISCARDED

    with (
        patch(
            "app.services.draft_service.get_draft",
            new=AsyncMock(return_value=draft),
        ),
        patch(
            "app.services.draft_service.discard_draft",
            new=AsyncMock(return_value=discarded_draft),
        ) as mock_discard,
    ):
        args = discard_draft.input_schema(draft_id=draft_id, confirmed=True)
        ctx = _make_ctx()
        result = await discard_draft.handler(args, ctx)

    mock_discard.assert_awaited_once_with(ctx.db, draft)
    assert result["action"] == "diagram.draft_discarded"
    assert result["target_type"] == "diagram"
    assert result["target_id"] == draft_id
    assert result["name"] == "Bye Draft"
