"""Agent node implementations and the shared ReAct loop.

Public surface re-exports the run_react primitives from :mod:`app.agents.nodes.base`
so callers can ``from app.agents.nodes import run_react, NodeConfig, NodeOutput``.

Concrete per-node modules (supervisor, planner, diagram, researcher, critic,
explainer) live alongside this ``base`` module and are added in tasks 018-024.
"""

from app.agents.nodes.base import (
    NodeConfig,
    NodeOutput,
    NodeStreamEvent,
    ToolCall,
    ToolExecutionResult,
    ToolExecutor,
    compose_messages_for_llm,
    run_react,
)

__all__ = [
    "NodeConfig",
    "NodeOutput",
    "NodeStreamEvent",
    "ToolCall",
    "ToolExecutionResult",
    "ToolExecutor",
    "compose_messages_for_llm",
    "run_react",
]
