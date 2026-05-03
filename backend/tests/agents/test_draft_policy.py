"""Tests for draft-policy resolution + mode clamping in app/agents/runtime.py.

Covers:
  * _resolve_active_draft_id  — all 5 branches (12+ cases total)
  * _clamp_mode               — api_key + user variants
  * _check_ask_policy_first_mutation — first-call / second-call behaviour

No real DB / LiteLLM / Redis.  A FakeDraftSession simulates returning lists of
open drafts so we can exercise branches 4 and 5 without touching Postgres.
"""
from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Minimal fake DB session — only needs to not raise on simple operations.
# The draft_service calls are patched out entirely.
# ---------------------------------------------------------------------------


class _FakeDB:
    """Bare-minimum AsyncSession stub used only to satisfy the type hint."""

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:  # noqa: ARG002
        raise NotImplementedError("FakeDB.execute should be patched in tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIAGRAM_ID = uuid4()
DRAFT_A_ID = str(uuid4())
DRAFT_B_ID = str(uuid4())


def _user_actor(access: str = "full") -> ActorRef:
    return ActorRef(
        kind="user",
        id=uuid4(),
        workspace_id=uuid4(),
        agent_access=access,  # type: ignore[arg-type]
    )


def _apikey_actor(*scopes: str) -> ActorRef:
    return ActorRef(
        kind="api_key",
        id=uuid4(),
        workspace_id=uuid4(),
        scopes=tuple(scopes),
    )


def _diagram_ctx(draft_id: UUID | None = None) -> ChatContext:
    return ChatContext(kind="diagram", id=DIAGRAM_ID, draft_id=draft_id)


def _workspace_ctx() -> ChatContext:
    return ChatContext(kind="workspace", id=uuid4())


def _patch_drafts(drafts: list[dict]):
    """Patch draft_service.get_drafts_for_diagram to return *drafts*."""
    return patch(
        "app.services.draft_service.get_drafts_for_diagram",
        new=AsyncMock(return_value=drafts),
    )


def _patch_get_draft(draft_obj: Any):
    """Patch draft_service.get_draft to return *draft_obj*."""
    return patch(
        "app.services.draft_service.get_draft",
        new=AsyncMock(return_value=draft_obj),
    )


# ===========================================================================
# _clamp_mode — 5 cases
# ===========================================================================


class TestClampMode:
    def test_apikey_write_scope_honors_full(self):
        actor = _apikey_actor("agents:write")
        assert _clamp_mode("full", actor) == "full"

    def test_apikey_admin_scope_honors_full(self):
        actor = _apikey_actor("agents:admin")
        assert _clamp_mode("full", actor) == "full"

    def test_apikey_read_scope_clamps_full_to_read_only(self):
        actor = _apikey_actor("agents:read")
        assert _clamp_mode("full", actor) == "read_only"

    def test_apikey_no_scopes_clamps_full_to_read_only(self):
        actor = _apikey_actor()
        assert _clamp_mode("full", actor) == "read_only"

    def test_user_none_access_raises_permission_error(self):
        actor = _user_actor("none")
        with pytest.raises(PermissionError):
            _clamp_mode("full", actor)

    def test_user_read_only_access_clamps_full(self):
        actor = _user_actor("read_only")
        assert _clamp_mode("full", actor) == "read_only"
        assert _clamp_mode("read_only", actor) == "read_only"

    def test_user_full_access_honors_requested_mode(self):
        actor = _user_actor("full")
        assert _clamp_mode("full", actor) == "full"
        assert _clamp_mode("read_only", actor) == "read_only"


# ===========================================================================
# _resolve_active_draft_id — all 5 branches
# ===========================================================================


class TestResolveActiveDraftId:
    """All async methods must run via pytest-asyncio."""

    # ── Branch 1: explicit draft_id in context ───────────────────────────────

    async def test_branch1_explicit_draft_id_returned(self):
        explicit = uuid4()
        ctx = _diagram_ctx(draft_id=explicit)
        db = _FakeDB()

        with _patch_get_draft(object()):  # draft "found" (any truthy object)
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="ask",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id == explicit
        assert choice is None

    async def test_branch1_explicit_draft_id_returned_even_if_service_fails(self):
        """draft_service failure must not block — we still return the draft_id."""
        explicit = uuid4()
        ctx = _diagram_ctx(draft_id=explicit)
        db = _FakeDB()

        with patch(
            "app.services.draft_service.get_draft",
            side_effect=RuntimeError("db offline"),
        ):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="drafts_only",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id == explicit
        assert choice is None

    # ── Branch 2: read_only mode ─────────────────────────────────────────────

    async def test_branch2_read_only_mode_returns_none(self):
        ctx = _diagram_ctx()
        db = _FakeDB()

        draft_id, choice = await _resolve_active_draft_id(
            db,
            chat_context=ctx,
            agent_edits_policy="drafts_only",
            mode="read_only",
            actor=_user_actor(),
        )
        assert draft_id is None
        assert choice is None

    # ── Branch 3: live_only policy ───────────────────────────────────────────

    async def test_branch3_live_only_returns_none(self):
        ctx = _diagram_ctx()
        db = _FakeDB()

        draft_id, choice = await _resolve_active_draft_id(
            db,
            chat_context=ctx,
            agent_edits_policy="live_only",
            mode="full",
            actor=_user_actor(),
        )
        assert draft_id is None
        assert choice is None

    # ── Branch 4a: drafts_only — 0 drafts → suspend ──────────────────────────

    async def test_branch4_drafts_only_zero_drafts_suspends(self):
        ctx = _diagram_ctx()
        db = _FakeDB()

        with _patch_drafts([]):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="drafts_only",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id is None
        assert choice is not None
        assert choice["kind"] == "draft_required"
        assert any(opt["id"] == "create_draft" for opt in choice["options"])
        assert "tool_call_id" in choice

    # ── Branch 4b: drafts_only — 1 draft → auto-pick ─────────────────────────

    async def test_branch4_drafts_only_single_draft_auto_picks(self):
        ctx = _diagram_ctx()
        db = _FakeDB()
        draft_uuid = uuid4()
        open_drafts = [
            {
                "draft_id": str(draft_uuid),
                "draft_name": "wip-payments",
                "draft_status": "open",
                "source_diagram_id": str(DIAGRAM_ID),
                "forked_diagram_id": str(uuid4()),
            }
        ]

        with _patch_drafts(open_drafts):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="drafts_only",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id == draft_uuid
        assert choice is None

    # ── Branch 4c: drafts_only — 2+ drafts → suspend with choices ────────────

    async def test_branch4_drafts_only_multiple_drafts_suspends_with_choices(self):
        ctx = _diagram_ctx()
        db = _FakeDB()
        open_drafts = [
            {
                "draft_id": DRAFT_A_ID,
                "draft_name": "feature-a",
                "draft_status": "open",
                "source_diagram_id": str(DIAGRAM_ID),
                "forked_diagram_id": str(uuid4()),
            },
            {
                "draft_id": DRAFT_B_ID,
                "draft_name": "feature-b",
                "draft_status": "open",
                "source_diagram_id": str(DIAGRAM_ID),
                "forked_diagram_id": str(uuid4()),
            },
        ]

        with _patch_drafts(open_drafts):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="drafts_only",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id is None
        assert choice is not None
        assert choice["kind"] == "draft_required"
        # Both existing drafts appear in options
        option_draft_ids = [
            o.get("draft_id") for o in choice["options"] if "draft_id" in o
        ]
        assert DRAFT_A_ID in option_draft_ids
        assert DRAFT_B_ID in option_draft_ids

    # ── Branch 5a: ask — 0 drafts → defer (requires_choice payload) ──────────

    async def test_branch5_ask_zero_drafts_defers_with_payload(self):
        ctx = _diagram_ctx()
        db = _FakeDB()

        with _patch_drafts([]):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="ask",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id is None
        assert choice is not None
        assert choice["kind"] == "draft_or_live"
        assert choice["message"].startswith("I'm about to make changes")
        option_ids = [o["id"] for o in choice["options"]]
        assert "create_draft" in option_ids
        assert "edit_live" in option_ids
        assert "tool_call_id" in choice

    # ── Branch 5b: ask — 1+ drafts → suspend with full options ───────────────

    async def test_branch5_ask_existing_drafts_includes_use_existing_option(self):
        ctx = _diagram_ctx()
        db = _FakeDB()
        open_drafts = [
            {
                "draft_id": DRAFT_A_ID,
                "draft_name": "wip-refactor",
                "draft_status": "open",
                "source_diagram_id": str(DIAGRAM_ID),
                "forked_diagram_id": str(uuid4()),
            }
        ]

        with _patch_drafts(open_drafts):
            draft_id, choice = await _resolve_active_draft_id(
                db,
                chat_context=ctx,
                agent_edits_policy="ask",
                mode="full",
                actor=_user_actor(),
            )

        assert draft_id is None
        assert choice is not None
        assert choice["kind"] == "draft_or_live"
        option_ids = [o["id"] for o in choice["options"]]
        assert "use_existing_draft" in option_ids
        assert "edit_live" in option_ids
        assert "create_draft" in option_ids
        # The use_existing option must carry the draft_id
        use_existing = next(
            o for o in choice["options"] if o["id"] == "use_existing_draft"
        )
        assert use_existing["draft_id"] == DRAFT_A_ID

    # ── Branch 5 edge: ask + non-diagram context → no choice ─────────────────

    async def test_branch5_ask_non_diagram_context_returns_none(self):
        ctx = _workspace_ctx()
        db = _FakeDB()

        draft_id, choice = await _resolve_active_draft_id(
            db,
            chat_context=ctx,
            agent_edits_policy="ask",
            mode="full",
            actor=_user_actor(),
        )

        assert draft_id is None
        assert choice is None


# ===========================================================================
# _check_ask_policy_first_mutation — 1 case (first call / second call)
# ===========================================================================


class TestCheckAskPolicyFirstMutation:
    _CHOICE_PAYLOAD = {
        "kind": "draft_or_live",
        "message": "I'm about to make changes. Choose where to apply them:",
        "options": [
            {"id": "create_draft", "label": "Create a draft (recommended)"},
            {"id": "edit_live", "label": "Edit live diagram"},
        ],
        "tool_call_id": None,
    }

    def test_first_call_returns_payload_and_sets_flag(self):
        state = _AskPolicyState()
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="ask",
            mode="full",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        assert result is self._CHOICE_PAYLOAD
        assert state.choice_presented is True

    def test_second_call_returns_none(self):
        state = _AskPolicyState()
        # First call — sets the flag.
        _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="ask",
            mode="full",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        # Second call — must be a no-op.
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="ask",
            mode="full",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        assert result is None

    def test_noop_when_policy_not_ask(self):
        state = _AskPolicyState()
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="live_only",
            mode="full",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        assert result is None
        assert state.choice_presented is False

    def test_noop_when_mode_read_only(self):
        state = _AskPolicyState()
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="ask",
            mode="read_only",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        assert result is None

    def test_noop_when_draft_already_resolved(self):
        state = _AskPolicyState()
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=uuid4(),
            agent_edits_policy="ask",
            mode="full",
            pending_requires_choice=self._CHOICE_PAYLOAD,
        )
        assert result is None

    def test_noop_when_no_pending_payload(self):
        state = _AskPolicyState()
        result = _check_ask_policy_first_mutation(
            state=state,
            active_draft_id=None,
            agent_edits_policy="ask",
            mode="full",
            pending_requires_choice=None,
        )
        assert result is None
