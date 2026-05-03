"""Tool correctness eval suite — deterministic, no golden JSON needed.

Assertions:
  1. Total registered tool count matches expected (guards against accidental
     removal or duplicate registration).
  2. Every tool's required_scope is in the valid scope hierarchy.
  3. All mutating tools have a non-empty permission_target.
  4. All delete_* tools have needs_confirmed_gate=True.
  5. No two tools share the same name (registry uniqueness).
  6. Every tool with required_scope='agents:admin' is also mutating=True
     (admin scope implies write-level access).
  7. All non-mutating tools have mutating=False (tautology guard against typos).
"""

from __future__ import annotations

# Force tool registration by importing all tool modules.
import app.agents.tools.drafts_tools  # noqa: F401
import app.agents.tools.model_tools  # noqa: F401
import app.agents.tools.reasoning_tools  # noqa: F401
import app.agents.tools.search_tools  # noqa: F401
import app.agents.tools.view_tools  # noqa: F401
import app.agents.tools.web_fetch  # noqa: F401
from app.agents.tools.base import all_tools

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Expected tool count as of task 057; update when tools are added/removed.
EXPECTED_TOOL_COUNT = 41

VALID_SCOPES = {"agents:read", "agents:invoke", "agents:write", "agents:admin"}

# Tools known to require the confirmed gate (delete_* and destructive ops).
# Keeping this explicit makes regressions obvious.
EXPECTED_CONFIRMED_GATE_TOOLS = {
    "delete_object",
    "delete_connection",
    "delete_diagram",
    "discard_draft",
    "unplace_from_diagram",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_count_matches_expected() -> None:
    """Guard against accidental tool additions or removals."""
    tools = all_tools()
    count = len(tools)
    assert count == EXPECTED_TOOL_COUNT, (
        f"Expected {EXPECTED_TOOL_COUNT} registered tools, got {count}. "
        f"Tools: {[t.name for t in tools]}"
    )


def test_all_tools_have_valid_scope() -> None:
    """Every tool's required_scope must be a recognized scope string."""
    bad: list[str] = []
    for t in all_tools():
        if t.required_scope not in VALID_SCOPES:
            bad.append(f"{t.name} → {t.required_scope!r}")
    assert bad == [], f"Tools with invalid required_scope: {bad}"


def test_mutating_tools_have_permission_target() -> None:
    """Mutating tools must declare a permission_target so ACL can enforce access."""
    bad: list[str] = []
    for t in all_tools():
        if t.mutating and not t.permission_target:
            bad.append(t.name)
    assert bad == [], f"Mutating tools missing permission_target: {bad}"


def test_delete_tools_have_confirmed_gate() -> None:
    """All tools in EXPECTED_CONFIRMED_GATE_TOOLS must have needs_confirmed_gate=True."""
    tools_by_name = {t.name: t for t in all_tools()}
    missing: list[str] = []
    for name in sorted(EXPECTED_CONFIRMED_GATE_TOOLS):
        t = tools_by_name.get(name)
        if t is None:
            missing.append(f"{name} (not registered)")
        elif not t.needs_confirmed_gate:
            missing.append(f"{name} (needs_confirmed_gate=False)")
    assert missing == [], f"Destructive tools missing confirmed gate: {missing}"


def test_no_duplicate_tool_names() -> None:
    """Registry must be unique by name — all_tools() already dedupes but verify."""
    tools = all_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names detected: "
        f"{[n for n in names if names.count(n) > 1]}"
    )


def test_admin_scope_tools_are_mutating() -> None:
    """Tools that require agents:admin should all be mutating (admin scope = writes)."""
    bad = [
        t.name for t in all_tools()
        if t.required_scope == "agents:admin" and not t.mutating
    ]
    assert bad == [], (
        f"Tools with agents:admin scope that are not mutating (unexpected): {bad}"
    )


def test_read_scope_tools_are_non_mutating() -> None:
    """Tools with agents:read scope should not be mutating."""
    bad = [
        t.name for t in all_tools()
        if t.required_scope == "agents:read" and t.mutating
    ]
    assert bad == [], (
        f"Tools with agents:read scope that are mutating (unexpected): {bad}"
    )
