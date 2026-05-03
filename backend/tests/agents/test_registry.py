"""Tests for app/agents/registry.py — AgentRegistry + AgentDescriptor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.registry import (
    AgentDescriptor,
    all_agents,
    clear,
    get,
    list_for_workspace,
    register,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_descriptor(
    agent_id: str = "test-agent",
    *,
    surfaces: frozenset | None = None,
    allowed_contexts: frozenset | None = None,
    supported_modes: tuple = ("read_only",),
    required_scope: str = "agents:read",
    tools_overview: tuple = (),
) -> AgentDescriptor:
    return AgentDescriptor(
        id=agent_id,
        name=f"Agent {agent_id}",
        description=f"Description for {agent_id}",
        surfaces=surfaces if surfaces is not None else frozenset({"chat_bubble"}),
        allowed_contexts=(
            allowed_contexts if allowed_contexts is not None else frozenset({"workspace"})
        ),
        supported_modes=supported_modes,
        required_scope=required_scope,
        tools_overview=tools_overview,
    )


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure a clean registry before and after each test."""
    clear()
    yield
    clear()


# ---------------------------------------------------------------------------
# 1. register + get round-trip
# ---------------------------------------------------------------------------


def test_register_and_get_round_trip():
    descriptor = _make_descriptor("alpha")
    register(descriptor)
    result = get("alpha")
    assert result is descriptor


def test_get_missing_raises_key_error():
    with pytest.raises(KeyError, match="not found in registry"):
        get("nonexistent")


def test_get_missing_error_lists_valid_ids():
    register(_make_descriptor("beta"))
    register(_make_descriptor("gamma"))
    with pytest.raises(KeyError) as exc_info:
        get("missing")
    # Error message should mention at least one of the valid IDs
    assert "beta" in str(exc_info.value) or "gamma" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 2. register overwrites same id
# ---------------------------------------------------------------------------


def test_register_overwrites_same_id():
    d1 = _make_descriptor("dup", required_scope="agents:read")
    d2 = _make_descriptor("dup", required_scope="agents:invoke")
    register(d1)
    register(d2)
    assert get("dup") is d2
    assert get("dup").required_scope == "agents:invoke"


# ---------------------------------------------------------------------------
# 3. all_agents sorted by id
# ---------------------------------------------------------------------------


def test_all_agents_sorted():
    register(_make_descriptor("zebra"))
    register(_make_descriptor("apple"))
    register(_make_descriptor("mango"))
    ids = [d.id for d in all_agents()]
    assert ids == sorted(ids)


def test_all_agents_empty_registry():
    assert all_agents() == []


# ---------------------------------------------------------------------------
# 4. list_for_workspace — scope filter (ApiKey actors)
# ---------------------------------------------------------------------------


def test_list_for_workspace_apikey_exact_scope_match():
    register(_make_descriptor("read-agent", required_scope="agents:read"))
    register(_make_descriptor("invoke-agent", required_scope="agents:invoke"))
    # Only agents:read scope → only read-agent passes
    result = list_for_workspace(actor_scopes={"agents:read"})
    ids = {d.id for d in result}
    assert "read-agent" in ids
    assert "invoke-agent" not in ids


def test_list_for_workspace_apikey_higher_scope_satisfies_lower():
    """agents:admin scope should satisfy agents:read requirement."""
    register(_make_descriptor("read-agent", required_scope="agents:read"))
    register(_make_descriptor("admin-agent", required_scope="agents:admin"))
    # admin scope satisfies agents:read and agents:admin
    result = list_for_workspace(actor_scopes={"agents:admin"})
    ids = {d.id for d in result}
    assert "read-agent" in ids
    assert "admin-agent" in ids


def test_list_for_workspace_apikey_invoke_scope_hierarchy():
    """agents:write satisfies agents:read, agents:invoke, agents:write but not admin."""
    register(_make_descriptor("read-agent", required_scope="agents:read"))
    register(_make_descriptor("invoke-agent", required_scope="agents:invoke"))
    register(_make_descriptor("write-agent", required_scope="agents:write"))
    register(_make_descriptor("admin-agent", required_scope="agents:admin"))

    result = list_for_workspace(actor_scopes={"agents:write"})
    ids = {d.id for d in result}
    assert "read-agent" in ids
    assert "invoke-agent" in ids
    assert "write-agent" in ids
    assert "admin-agent" not in ids


def test_list_for_workspace_apikey_empty_scopes_returns_nothing():
    register(_make_descriptor("read-agent", required_scope="agents:read"))
    result = list_for_workspace(actor_scopes=set())
    assert result == []


# ---------------------------------------------------------------------------
# 5. list_for_workspace agent_access='none' → empty
# ---------------------------------------------------------------------------


def test_list_for_workspace_agent_access_none_returns_empty():
    register(_make_descriptor("agent-a"))
    register(_make_descriptor("agent-b"))
    result = list_for_workspace(workspace_agent_access="none")
    assert result == []


# ---------------------------------------------------------------------------
# 6. list_for_workspace agent_access='read_only' → only descriptors with read_only
# ---------------------------------------------------------------------------


def test_list_for_workspace_agent_access_read_only_filters_correctly():
    register(_make_descriptor("read-only-agent", supported_modes=("read_only",)))
    register(_make_descriptor("full-only-agent", supported_modes=("full",)))
    register(_make_descriptor("both-modes-agent", supported_modes=("full", "read_only")))

    result = list_for_workspace(workspace_agent_access="read_only")
    ids = {d.id for d in result}
    assert "read-only-agent" in ids
    assert "both-modes-agent" in ids
    assert "full-only-agent" not in ids


def test_list_for_workspace_agent_access_full_returns_all():
    register(_make_descriptor("read-only-agent", supported_modes=("read_only",)))
    register(_make_descriptor("full-only-agent", supported_modes=("full",)))

    result = list_for_workspace(workspace_agent_access="full")
    ids = {d.id for d in result}
    assert "read-only-agent" in ids
    assert "full-only-agent" in ids


# ---------------------------------------------------------------------------
# 7. list_for_workspace surface filter
# ---------------------------------------------------------------------------


def test_list_for_workspace_surface_filter():
    register(_make_descriptor("chat-agent", surfaces=frozenset({"chat_bubble"})))
    register(_make_descriptor("a2a-agent", surfaces=frozenset({"a2a"})))
    register(_make_descriptor("multi-agent", surfaces=frozenset({"chat_bubble", "a2a"})))

    chat_result = list_for_workspace(surface_filter="chat_bubble")
    chat_ids = {d.id for d in chat_result}
    assert "chat-agent" in chat_ids
    assert "multi-agent" in chat_ids
    assert "a2a-agent" not in chat_ids

    a2a_result = list_for_workspace(surface_filter="a2a")
    a2a_ids = {d.id for d in a2a_result}
    assert "a2a-agent" in a2a_ids
    assert "multi-agent" in a2a_ids
    assert "chat-agent" not in a2a_ids


# ---------------------------------------------------------------------------
# 8. clear empties registry
# ---------------------------------------------------------------------------


def test_clear_empties_registry():
    register(_make_descriptor("agent-x"))
    register(_make_descriptor("agent-y"))
    assert len(all_agents()) == 2
    clear()
    assert all_agents() == []
    with pytest.raises(KeyError):
        get("agent-x")


# ---------------------------------------------------------------------------
# 9. AgentDescriptor defaults and frozen behaviour
# ---------------------------------------------------------------------------


def test_agent_descriptor_defaults():
    d = AgentDescriptor(id="minimal", name="Minimal", description="Min agent")
    assert d.schema_version == "v1"
    assert d.graph is None
    assert d.surfaces == frozenset()
    assert d.allowed_contexts == frozenset()
    assert d.supported_modes == ("read_only",)
    assert d.required_scope == "agents:read"
    assert d.tools_overview == ()
    assert d.default_turn_limit == 200
    assert d.default_budget_usd == Decimal("1.00")
    assert d.default_budget_scope == "per_invocation"
    assert d.streaming is True


def test_agent_descriptor_is_frozen():
    d = AgentDescriptor(id="frozen", name="Frozen", description="Test")
    with pytest.raises((AttributeError, TypeError)):
        d.name = "Changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 10. Combined filters
# ---------------------------------------------------------------------------


def test_list_for_workspace_combined_scope_and_surface():
    """apikey scope + surface_filter applied together."""
    register(
        _make_descriptor(
            "chat-read",
            required_scope="agents:read",
            surfaces=frozenset({"chat_bubble"}),
        )
    )
    register(
        _make_descriptor(
            "a2a-invoke",
            required_scope="agents:invoke",
            surfaces=frozenset({"a2a"}),
        )
    )
    register(
        _make_descriptor(
            "chat-invoke",
            required_scope="agents:invoke",
            surfaces=frozenset({"chat_bubble"}),
        )
    )

    # agents:invoke scope, chat_bubble surface only
    result = list_for_workspace(
        actor_scopes={"agents:invoke"},
        surface_filter="chat_bubble",
    )
    ids = {d.id for d in result}
    assert "chat-read" in ids     # read satisfied by invoke, has chat_bubble
    assert "chat-invoke" in ids   # invoke satisfied, has chat_bubble
    assert "a2a-invoke" not in ids  # invoke satisfied but no chat_bubble
