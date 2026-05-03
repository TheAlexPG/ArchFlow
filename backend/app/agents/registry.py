"""
AgentRegistry — maps agent IDs to AgentDescriptor instances.
Descriptors are registered at application startup via register_builtin_agents().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Surface = Literal["chat_bubble", "inline_button", "a2a"]
ContextKind = Literal["workspace", "diagram", "object", "none"]
Mode = Literal["full", "read_only"]

# Scope hierarchy (broader scopes imply narrower ones)
_SCOPE_HIERARCHY: dict[str, int] = {
    "agents:read": 0,
    "agents:invoke": 1,
    "agents:write": 2,
    "agents:admin": 3,
}


@dataclass(frozen=True)
class AgentDescriptor:
    """Metadata and wiring for a single registered agent."""

    id: str
    name: str
    description: str
    schema_version: str = "v1"
    graph: Any = None  # CompiledStateGraph; Any for now
    surfaces: frozenset[Surface] = field(default_factory=frozenset)
    allowed_contexts: frozenset[ContextKind] = field(default_factory=frozenset)
    supported_modes: tuple[Mode, ...] = ("read_only",)
    # 'agents:read' | 'agents:invoke' | 'agents:write' | 'agents:admin'
    required_scope: str = "agents:read"
    tools_overview: tuple[str, ...] = ()  # tool names for discovery preview
    default_turn_limit: int = 200
    default_budget_usd: Decimal = Decimal("1.00")
    default_budget_scope: Literal["per_invocation", "per_request"] = "per_invocation"
    streaming: bool = True


# Module-level registry store
_REGISTRY: dict[str, AgentDescriptor] = {}


def register(descriptor: AgentDescriptor) -> None:
    """Idempotent: overwrites existing entry with same id (allows hot reload in tests)."""
    _REGISTRY[descriptor.id] = descriptor


def get(agent_id: str) -> AgentDescriptor:
    """Raises KeyError with helpful message listing valid IDs if not found."""
    if agent_id not in _REGISTRY:
        valid = sorted(_REGISTRY.keys())
        raise KeyError(
            f"Agent {agent_id!r} not found in registry. Valid IDs: {valid}"
        )
    return _REGISTRY[agent_id]


def all_agents() -> list[AgentDescriptor]:
    """Sorted by id."""
    return sorted(_REGISTRY.values(), key=lambda d: d.id)


def list_for_workspace(
    *,
    actor_scopes: set[str] | None = None,  # for ApiKey actors
    workspace_agent_access: Literal["none", "read_only", "full"] | None = None,  # for User actors
    surface_filter: Surface | None = None,
) -> list[AgentDescriptor]:
    """Filter by:
    - actor_scopes (None for User → no scope filter); for ApiKey: required_scope must be in scopes
    - workspace_agent_access: 'none' → []; 'read_only' → only descriptors with 'read_only' mode;
      'full' → all
    - surface_filter: only descriptors that have this surface
    """
    # 'none' access → empty list immediately
    if workspace_agent_access == "none":
        return []

    results: list[AgentDescriptor] = []

    for descriptor in all_agents():
        # Scope filter for ApiKey actors (actor_scopes is not None)
        if actor_scopes is not None and not _scope_satisfied(
            descriptor.required_scope, actor_scopes
        ):
            continue

        # workspace_agent_access filter for User actors
        if workspace_agent_access == "read_only" and "read_only" not in descriptor.supported_modes:
            continue
        # workspace_agent_access == "full" or None → no mode restriction

        # Surface filter
        if surface_filter is not None and surface_filter not in descriptor.surfaces:
            continue

        results.append(descriptor)

    return results


def _scope_satisfied(required_scope: str, actor_scopes: set[str]) -> bool:
    """Return True if actor_scopes contains required_scope or any higher scope."""
    required_level = _SCOPE_HIERARCHY.get(required_scope, 0)
    for scope in actor_scopes:
        level = _SCOPE_HIERARCHY.get(scope, -1)
        if level >= required_level:
            return True
    return False


def clear() -> None:
    """Test helper. Empties registry."""
    _REGISTRY.clear()
