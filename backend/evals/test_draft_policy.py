"""Draft policy eval suite — deterministic, no LLM.

Tests branches 1–5 of _resolve_active_draft_id, _clamp_mode variants,
and _check_ask_policy_first_mutation idempotency.

Cases are driven from golden/draft_policy.json so new branches can be
added without touching Python.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents.runtime import (
    ActorRef,
    ChatContext,
    _AskPolicyState,
    _check_ask_policy_first_mutation,
    _clamp_mode,
    _resolve_active_draft_id,
)

GOLDEN = json.loads((Path(__file__).parent / "golden" / "draft_policy.json").read_text())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_actor(case: dict) -> ActorRef:
    kind = case.get("actor_kind", "user")
    return ActorRef(
        kind=kind,
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=tuple(case.get("actor_scopes", [])),
        agent_access=case.get("actor_agent_access"),
    )


def _make_chat_context(raw: dict) -> ChatContext:
    draft_id_str = raw.get("draft_id")
    context_id_str = raw.get("id")
    return ChatContext(
        kind=raw.get("kind", "none"),
        id=UUID(context_id_str) if context_id_str else None,
        draft_id=UUID(draft_id_str) if draft_id_str else None,
    )


# ---------------------------------------------------------------------------
# _clamp_mode cases
# ---------------------------------------------------------------------------


_CLAMP_CASES = [c for c in GOLDEN if c.get("test_type") == "clamp_mode"]


@pytest.mark.parametrize("case", _CLAMP_CASES, ids=lambda c: c["id"])
def test_clamp_mode(case: dict) -> None:
    actor = _make_actor(case)
    requested = case["requested_mode"]
    expected_exc = case.get("expected_exception")
    expected_mode = case.get("expected_mode")

    if expected_exc == "PermissionError":
        with pytest.raises(PermissionError):
            _clamp_mode(requested, actor)
    else:
        result = _clamp_mode(requested, actor)
        assert result == expected_mode, f"Expected {expected_mode!r}, got {result!r}"


# ---------------------------------------------------------------------------
# _check_ask_policy_first_mutation cases
# ---------------------------------------------------------------------------


_ASK_CASES = [c for c in GOLDEN if c.get("test_type") == "ask_policy"]


@pytest.mark.parametrize("case", _ASK_CASES, ids=lambda c: c["id"])
def test_check_ask_policy_first_mutation(case: dict) -> None:
    state = _AskPolicyState(choice_presented=case.get("choice_already_presented", False))
    draft_id_str = case.get("active_draft_id")
    active_draft_id = UUID(draft_id_str) if draft_id_str else None

    result = _check_ask_policy_first_mutation(
        state=state,
        active_draft_id=active_draft_id,
        agent_edits_policy=case["policy"],
        mode=case["mode"],
        pending_requires_choice=case.get("pending_payload"),
    )
    expected = case["expected_result"]
    assert result == expected, f"Expected {expected!r}, got {result!r}"


# ---------------------------------------------------------------------------
# _resolve_active_draft_id cases
# ---------------------------------------------------------------------------


_RESOLVE_CASES = [
    c for c in GOLDEN
    if c.get("test_type") not in ("clamp_mode", "ask_policy")
]


class _FakeResolveDB:
    """Minimal async DB stub for _resolve_active_draft_id — patches draft_service."""
    pass


@pytest.mark.parametrize("case", _RESOLVE_CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_resolve_active_draft_id(case: dict) -> None:
    chat_ctx_raw = case["chat_context"]
    chat_ctx = _make_chat_context(chat_ctx_raw)
    actor = _make_actor(case)
    open_drafts = case.get("open_drafts", [])
    db = _FakeResolveDB()

    # Patch draft_service functions so we avoid real DB.
    async def _fake_get_draft(_db: Any, draft_id: UUID) -> dict:
        return {"draft_id": str(draft_id)}

    async def _fake_get_drafts_for_diagram(_db: Any, diagram_id: UUID) -> list:
        return open_drafts

    with (
        patch(
            "app.services.draft_service.get_draft",
            new=AsyncMock(side_effect=_fake_get_draft),
        ),
        patch(
            "app.services.draft_service.get_drafts_for_diagram",
            new=AsyncMock(side_effect=_fake_get_drafts_for_diagram),
        ),
    ):
        draft_id, requires_choice = await _resolve_active_draft_id(
            db,
            chat_context=chat_ctx,
            agent_edits_policy=case["agent_edits_policy"],
            mode=case["mode"],
            actor=actor,
        )

    # Assert draft_id
    expected_draft_id_str = case.get("expected_draft_id")
    if expected_draft_id_str is None:
        assert draft_id is None, f"Expected draft_id=None, got {draft_id}"
    else:
        assert draft_id == UUID(expected_draft_id_str), (
            f"Expected draft_id={expected_draft_id_str}, got {draft_id}"
        )

    # Assert requires_choice
    if "expected_requires_choice" in case and case["expected_requires_choice"] is None:
        assert requires_choice is None, f"Expected requires_choice=None, got {requires_choice}"
    elif "expected_requires_choice_kind" in case:
        assert requires_choice is not None, "Expected a requires_choice payload, got None"
        assert requires_choice.get("kind") == case["expected_requires_choice_kind"], (
            f"Expected kind={case['expected_requires_choice_kind']!r}, "
            f"got {requires_choice.get('kind')!r}"
        )
