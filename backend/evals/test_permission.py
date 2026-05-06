"""Permission eval suite — deterministic. Asserts ToolDenied/denied status
for unauthorized tool invocations and verifies filter_tools scope gating.

No LLM calls. DB mocked via patch.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import app.agents.tools.drafts_tools  # noqa: F401  # Force tool registration before tests run.
import app.agents.tools.model_tools  # noqa: F401
import app.agents.tools.reasoning_tools  # noqa: F401
import app.agents.tools.search_tools  # noqa: F401
import app.agents.tools.view_tools  # noqa: F401
from app.agents.runtime import ActorRef
from app.agents.tools.base import (
    ToolContext,
    execute_tool,
    filter_tools,
)

GOLDEN = json.loads((Path(__file__).parent / "golden" / "permission.json").read_text())

_SCOPE_ORDER = {"agents:read": 0, "agents:invoke": 1, "agents:write": 2, "agents:admin": 3}


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


def _make_tool_ctx(actor: ActorRef, mode: str) -> ToolContext:
    return ToolContext(
        db=MagicMock(),
        actor=actor,
        workspace_id=uuid4(),
        chat_context={"kind": "workspace", "id": None},
        session_id=uuid4(),
        agent_id="general",
        agent_runtime_mode=mode,
        active_draft_id=None,
    )


# ---------------------------------------------------------------------------
# filter_tools cases
# ---------------------------------------------------------------------------


_FILTER_CASES = [c for c in GOLDEN if c.get("test_type") == "filter_tools"]
_EXEC_CASES = [c for c in GOLDEN if c.get("test_type") != "filter_tools"]


@pytest.mark.parametrize("case", _FILTER_CASES, ids=lambda c: c["id"])
def test_filter_tools_permission(case: dict) -> None:
    scope = case["scope"]
    mode = case["mode"]
    tools = filter_tools(scope=scope, mode=mode)

    if case.get("expected_no_mutating"):
        mutating_names = [t.name for t in tools if t.mutating]
        assert mutating_names == [], (
            f"read_only mode should hide mutating tools; found: {mutating_names}"
        )

    if "expected_max_scope" in case:
        max_allowed_level = _SCOPE_ORDER[case["expected_max_scope"]]
        over_scope = [
            t.name for t in tools
            if _SCOPE_ORDER.get(t.required_scope, 99) > max_allowed_level
        ]
        assert over_scope == [], (
            f"Tools above scope {case['expected_max_scope']!r} leaked: {over_scope}"
        )


# ---------------------------------------------------------------------------
# execute_tool scope / mode guard cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _EXEC_CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_execute_tool_permission(case: dict) -> None:
    actor = _make_actor(case)
    mode: str = case.get("agent_runtime_mode", "full")
    ctx = _make_tool_ctx(actor, mode)

    tool_call = {
        "id": "tc-001",
        "name": case["tool_name"],
        "arguments": case.get("tool_args", {}),
    }

    # Patch access_service to avoid DB; ACL layers are all bypassed by the
    # scope/mode guards before reaching the actual service layer in denied cases.
    with (
        patch("app.services.access_service.can_read_diagram", new=AsyncMock(return_value=True)),
        patch("app.services.access_service.can_write_diagram", new=AsyncMock(return_value=True)),
        patch("app.services.diagram_service.get_diagram", new=AsyncMock(return_value=MagicMock())),
        patch("app.services.object_service.get_object", new=AsyncMock(return_value=MagicMock())),
    ):
        result = await execute_tool(tool_call, ctx)

    if "expected_status" in case:
        assert result.status == case["expected_status"], (
            f"[{case['id']}] Expected status={case['expected_status']!r}, "
            f"got {result.status!r}. Content: {result.content}"
        )
    if "expected_status_not" in case:
        assert result.status != case["expected_status_not"], (
            f"[{case['id']}] Expected status NOT={case['expected_status_not']!r}, "
            f"but got {result.status!r}"
        )
