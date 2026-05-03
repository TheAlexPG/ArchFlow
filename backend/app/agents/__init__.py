"""
Public re-exports for the agents package.
Downstream code imports from app.agents; this module exposes the top-level surface.
"""

from app.agents import builtin, errors, layout, registry, runtime, state, tools
from app.agents.context_manager import (
    STRATEGY_REGISTRY,
    CompactionResult,
    CompactionStrategy,
    ContextManager,
)
from app.agents.limits import (
    HealthCheckResult,
    LimitsEnforcer,
    RuntimeCounters,
    RuntimeLimits,
)
from app.agents.llm import LLMCallMetadata, LLMClient, LLMResult
from app.agents.registry import (
    AgentDescriptor,
    all_agents,
    get,
    list_for_workspace,
    register,
)
from app.agents.runtime import (
    ActorRef,
    ChatContext,
    InvokeRequest,
    InvokeResult,
    SSEEvent,
    invoke,
    stream,
)

__all__ = [
    "STRATEGY_REGISTRY",
    "ActorRef",
    "AgentDescriptor",
    "ChatContext",
    "CompactionResult",
    "CompactionStrategy",
    "ContextManager",
    "HealthCheckResult",
    "InvokeRequest",
    "InvokeResult",
    "LLMCallMetadata",
    "LLMClient",
    "LLMResult",
    "LimitsEnforcer",
    "RuntimeCounters",
    "RuntimeLimits",
    "SSEEvent",
    "all_agents",
    "builtin",
    "errors",
    "get",
    "invoke",
    "layout",
    "list_for_workspace",
    "register",
    "registry",
    "runtime",
    "state",
    "stream",
    "tools",
]
