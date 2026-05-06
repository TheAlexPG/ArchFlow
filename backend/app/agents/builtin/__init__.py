"""Built-in agent implementations: general, researcher, diagram_explainer.

Provides :func:`register_builtin_agents` — call once at application startup
(e.g., from the FastAPI ``lifespan`` context) so ``app.agents.registry``
knows about every shipped agent.

Idempotent: ``register`` overwrites by id, so re-running the function (e.g.,
in tests) is safe.
"""

from __future__ import annotations

from app.agents.registry import register


def register_builtin_agents() -> None:
    """Register all builtin agents with the global registry.

    Adds ``general``, ``researcher``, and ``diagram-explainer`` descriptors.
    Each descriptor builds its compiled LangGraph eagerly via
    ``get_descriptor`` — call this exactly once at app startup.

    Imports are lazy / function-scoped so simply importing this package does
    not eagerly compile every graph (and pull in langgraph) — that cost only
    lands when an actual app boot triggers registration.
    """
    from app.agents.builtin.diagram_explainer import graph as diagram_explainer_graph
    from app.agents.builtin.general import graph as general_graph
    from app.agents.builtin.researcher import graph as researcher_graph

    register(general_graph.get_descriptor())
    register(researcher_graph.get_descriptor())
    register(diagram_explainer_graph.get_descriptor())


__all__ = ["register_builtin_agents"]
