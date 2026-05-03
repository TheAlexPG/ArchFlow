"""General agent LangGraph wiring: supervisor + planner + diagram + researcher + critic + finalize.

Topology (per spec §3.3)::

    START → supervisor
    supervisor ─┬─► planner    (delegate_to_planner)
                ├─► diagram    (delegate_to_diagram)
                ├─► researcher (delegate_to_researcher)
                ├─► critic     (delegate_to_critic)
                └─► finalize   (finalize tool, or unrecognised → defensive)

    planner    → diagram     (planner produces Plan; diagram executes)
    diagram    → supervisor  (loop back so supervisor can decide next step)
    researcher → supervisor
    critic     ─┬─► finalize  (APPROVE, or REVISE & iteration ≥ MAX_CRITIQUE_LOOPS)
                └─► planner   (REVISE & iteration < MAX_CRITIQUE_LOOPS, with iteration++)
    finalize   → END

Loop bounds:
  * ``MAX_TOTAL_STEPS = 15`` — informational; the runtime layer (task 016)
    enforces this via :class:`LimitsEnforcer` (turn counter), not the graph.
  * ``MAX_CRITIQUE_LOOPS = 2`` — enforced here in :func:`_critic_routes_next`.

Compiled with ``checkpointer=None`` — persistence lives in
``agent_chat_session`` row + replay-on-resume from ``state['messages']``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from app.agents.registry import AgentDescriptor
from app.agents.state import AgentState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.types import RunnableConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Loop bounds (spec §3.3)
# ---------------------------------------------------------------------------

MAX_TOTAL_STEPS = 15
MAX_CRITIQUE_LOOPS = 2


# ---------------------------------------------------------------------------
# Constants — supervisor delegation tool names → node names
# ---------------------------------------------------------------------------

_DELEGATE_TO_NODE: dict[str, str] = {
    "delegate_to_planner": "planner",
    "delegate_to_diagram": "diagram",
    "delegate_to_researcher": "researcher",
    "delegate_to_critic": "critic",
    "finalize": "finalize",
}


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------


def _last_assistant_tool_call_name(messages: list[dict] | None) -> str | None:
    """Return the tool call name from the **most recent** assistant turn,
    or ``None`` when that turn has no tool_calls (= supervisor already
    answered with prose and we should finalize).

    Critical: we do NOT skip past a text-only assistant turn to find an
    older delegate_to_* tool call. Doing so caused infinite re-delegation:
    after researcher returned, supervisor #2 wrote a final reply (no
    tool_calls), the router then walked further back, found supervisor #1's
    ``delegate_to_researcher`` and re-launched the researcher node. The
    second-pass researcher would then loop the same tools and burn another
    25 seconds for nothing.
    """
    for msg in reversed(messages or []):
        if msg.get("role") != "assistant":
            continue
        # Found the most recent assistant turn — its presence/absence of
        # tool_calls is what decides the next graph hop.
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return None
        last = tool_calls[-1]
        fn = last.get("function") or {}
        return fn.get("name") or last.get("name")
    return None


def _supervisor_routes_next(state: AgentState) -> str:
    """Conditional edge from supervisor.

    Inspects the most recent assistant tool call in ``state['messages']`` and
    maps the supervisor's delegation/finalize tool names to LangGraph node
    names. Falls back to ``'finalize'`` defensively when no recognised tool
    call is present (avoids dangling runs).

    Also short-circuits to ``finalize`` when the supervisor visit count
    exceeds :data:`MAX_TOTAL_STEPS` — protects against runaway delegation
    loops with local models that mis-handle the protocol (e.g. Qwen via
    LM Studio sometimes oscillates supervisor↔researcher forever when the
    delegate keeps returning empty findings).
    """
    visits = int(state.get("supervisor_visits") or 0)
    if visits >= MAX_TOTAL_STEPS:
        logger.warning(
            "supervisor router: supervisor visit limit (%d) reached → finalize",
            MAX_TOTAL_STEPS,
        )
        return "finalize"

    messages = state.get("messages") or []
    name = _last_assistant_tool_call_name(messages)
    if name is None:
        # Defensive: supervisor exited without delegating → finalize.
        logger.debug("supervisor router: no tool call in messages → finalize")
        return "finalize"
    target = _DELEGATE_TO_NODE.get(name)
    if target is None:
        logger.debug(
            "supervisor router: unrecognised tool call %r → finalize", name
        )
        return "finalize"
    return target


def _critic_routes_next(state: AgentState) -> str:
    """Conditional edge after critic.

    Routing rules:
      * ``critique.verdict == 'APPROVE'`` → ``finalize``.
      * ``critique.verdict == 'REVISE'`` and
        ``state['iteration'] < MAX_CRITIQUE_LOOPS`` → ``planner``.
      * Otherwise (including missing critique or REVISE at limit) → ``finalize``.

    Note: the iteration counter is incremented inside :func:`critic_node`
    (the LangGraph wrapper) when it decides to route back to planner. We do
    NOT mutate state here — conditional-edge functions are read-only by
    convention.
    """
    critique = state.get("critique")
    if critique is None:
        return "finalize"

    if hasattr(critique, "verdict"):
        verdict = critique.verdict
    elif isinstance(critique, dict):
        verdict = critique.get("verdict")
    else:
        verdict = None

    if verdict == "APPROVE":
        return "finalize"

    iteration = state.get("iteration") or 0
    if verdict == "REVISE" and iteration < MAX_CRITIQUE_LOOPS:
        return "planner"

    # REVISE & at-limit, or unrecognised verdict → finalize defensively.
    return "finalize"


def _planner_routes_next(state: AgentState) -> str:  # noqa: ARG001
    """Static edge after planner: always go to diagram (planner emits a Plan;
    the diagram-agent executes it). Kept as a function for symmetry / testing."""
    return "diagram"


def _diagram_routes_next(state: AgentState) -> str:  # noqa: ARG001
    """Static edge after diagram: always loop back to supervisor so it can
    decide whether to delegate to critic, run another planner pass, or finalize."""
    return "supervisor"


def _researcher_routes_next(state: AgentState) -> str:  # noqa: ARG001
    """Static edge after researcher: back to supervisor."""
    return "supervisor"


# ---------------------------------------------------------------------------
# Dependency extraction helper
# ---------------------------------------------------------------------------


def _extract_deps(config: Optional[RunnableConfig]) -> tuple[Any, Any, Any, Any]:
    """Pull (enforcer, context_manager, tool_executor, call_metadata_base)
    out of LangGraph ``config['configurable']``.

    Raises ``RuntimeError`` if any are missing — these *must* be injected by
    the runtime (task 016) before invoking the graph.
    """
    cfg_extras: dict = {}
    if config is not None and (isinstance(config, dict) or hasattr(config, "get")):
        cfg_extras = config.get("configurable", {}) or {}

    enforcer = cfg_extras.get("enforcer")
    context_manager = cfg_extras.get("context_manager")
    tool_executor = cfg_extras.get("tool_executor")
    call_metadata_base = cfg_extras.get("call_metadata_base")

    missing = [
        n
        for n, v in (
            ("enforcer", enforcer),
            ("context_manager", context_manager),
            ("tool_executor", tool_executor),
            ("call_metadata_base", call_metadata_base),
        )
        if v is None
    ]
    if missing:
        raise RuntimeError(
            "general agent graph requires "
            f"{missing} in config['configurable']; "
            "the runtime layer must inject these before invoking the graph."
        )
    return enforcer, context_manager, tool_executor, call_metadata_base


def _get_tracer(config: Optional[RunnableConfig]) -> Any | None:
    """Pull the (optional) :class:`AgentTracer` out of config. Returns ``None``
    when Langfuse isn't wired — every tracer method handles ``None`` gracefully
    so node wrappers don't need to special-case the disabled path.
    """
    if config is None:
        return None
    if isinstance(config, dict) or hasattr(config, "get"):
        return (config.get("configurable") or {}).get("agent_tracer")
    return None


def _strip_subagent_messages(patch: dict) -> dict:
    """Remove ``messages`` from a sub-agent's state_patch.

    Sub-agents run on an isolated message list (see
    :func:`app.agents.nodes.base.isolated_state_for_subagent`) — propagating
    that list back into the global LangGraph state would (a) leak the
    sub-agent's tool call chatter into the user-visible transcript, and (b)
    overwrite the supervisor's history with an isolated single-user-message
    list, losing the original conversation.
    """
    patch.pop("messages", None)
    return patch


async def _drain_with_tracing(
    *,
    node_run,
    tracer: Any,
    span_name: str,
    base_call_meta: Any,
):
    """Drive a node's run() iterator while opening a Langfuse span around it.

    Returns ``(output, forced, call_meta_for_node)``. Tool calls observed
    in the stream are emitted as Langfuse events under the span. Generations
    that LiteLLM auto-traces nest under the span via the
    ``parent_observation_id`` carried on ``call_meta_for_node``.

    Callers wrap their own ``node.run(...)`` with this helper instead of
    iterating the events directly.
    """
    from dataclasses import replace as _replace

    span_id: str | None = None
    if tracer is not None and tracer.enabled:
        span_id = tracer.start_node_span(name=span_name)

    call_meta_for_node = (
        _replace(base_call_meta, parent_observation_id=span_id)
        if span_id
        else base_call_meta
    )

    output = None
    forced: str | None = None
    pending: dict[str, dict] = {}
    try:
        async for ev in node_run(call_meta_for_node):
            kind = ev.kind
            if kind == "tool_call":
                pending[ev.payload.get("id") or ""] = {
                    "name": ev.payload.get("name"),
                    "arguments": ev.payload.get("arguments"),
                }
            elif kind == "tool_result" and tracer is not None and span_id is not None:
                meta = pending.pop(ev.payload.get("id") or "", {})
                # Prefer the full content (serialised tool result) over the
                # short preview so Langfuse shows the actual data the LLM
                # received, not just an "<tool> ok" status string.
                output_payload = ev.payload.get("content") or ev.payload.get("preview")
                tracer.log_tool_event(
                    parent_id=span_id,
                    name=meta.get("name") or "tool",
                    input_payload=meta.get("arguments"),
                    output_payload=output_payload,
                    status=ev.payload.get("status"),
                )
            elif kind == "forced_finalize":
                forced = ev.payload.get("reason")
            elif kind == "finished":
                output = ev.payload["output"]
    finally:
        if tracer is not None:
            tracer.end_node_span(
                span_id=span_id,
                output={
                    "forced_finalize": forced,
                    "tool_calls_made": getattr(output, "tool_calls_made", 0),
                },
                level="ERROR" if forced else None,
            )

    return output, forced


# ---------------------------------------------------------------------------
# Node wrappers — drain async-iterator nodes, return state delta dicts.
# ---------------------------------------------------------------------------


async def supervisor_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """LangGraph node: drains supervisor.run() iterator, returns state delta.

    The supervisor's run() already merges ``scratchpad`` / ``final_message`` /
    ``forced_finalize`` into ``output.state_patch`` — we just forward it.
    """
    from app.agents.builtin.general.nodes import supervisor

    enforcer, cm, tool_executor, call_meta = _extract_deps(config)
    tracer = _get_tracer(config)
    visit = int(state.get("supervisor_visits") or 0) + 1
    logger.warning("graph: supervisor_node ENTER visit=%d", visit)

    output, forced = await _drain_with_tracing(
        node_run=lambda meta: supervisor.run(
            state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=tool_executor,
            call_metadata_base=meta,
        ),
        tracer=tracer,
        span_name="supervisor",
        base_call_meta=call_meta,
    )

    patch: dict = dict(output.state_patch) if output else {}
    if forced and "forced_finalize" not in patch:
        patch["forced_finalize"] = forced
    # Track supervisor visits so the router can short-circuit runaway loops.
    patch["supervisor_visits"] = visit
    logger.warning(
        "graph: supervisor_node EXIT visit=%d forced=%s final_message_set=%s delegate=%s",
        visit,
        forced,
        bool(patch.get("final_message")),
        (patch.get("delegate_brief") or {}).get("kind"),
    )
    return patch


async def planner_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """LangGraph node: drains planner.run() iterator, lifts structured Plan
    into ``state_patch['plan']``."""
    from app.agents.builtin.general.nodes import planner
    from app.agents.nodes.base import isolated_state_for_subagent

    enforcer, cm, tool_executor, call_meta = _extract_deps(config)
    tracer = _get_tracer(config)
    logger.warning("graph: planner_node ENTER")
    iso_state = isolated_state_for_subagent(state)

    output, forced = await _drain_with_tracing(
        node_run=lambda meta: planner.run(
            iso_state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=tool_executor,
            call_metadata_base=meta,
        ),
        tracer=tracer,
        span_name="planner",
        base_call_meta=call_meta,
    )

    patch: dict = _strip_subagent_messages(dict(output.state_patch) if output else {})
    logger.warning("graph: planner_node EXIT forced=%s plan=%s", forced, bool(output and output.structured))
    # Planner.run() does NOT inject the plan; we do it here so AgentState.plan
    # gets populated for downstream nodes (diagram, critic, finalize).
    if output is not None and output.structured is not None:
        patch["plan"] = output.structured
    if forced and "forced_finalize" not in patch:
        patch["forced_finalize"] = forced
    return patch


async def diagram_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """LangGraph node: drains diagram.run() iterator. The diagram node already
    augments ``state_patch`` with ``applied_changes`` / ``plan_steps_done``."""
    from app.agents.builtin.general.nodes import diagram
    from app.agents.nodes.base import isolated_state_for_subagent

    enforcer, cm, tool_executor, call_meta = _extract_deps(config)
    tracer = _get_tracer(config)
    logger.warning("graph: diagram_node ENTER")
    iso_state = isolated_state_for_subagent(state)

    output, forced = await _drain_with_tracing(
        node_run=lambda meta: diagram.run(
            iso_state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=tool_executor,
            call_metadata_base=meta,
        ),
        tracer=tracer,
        span_name="diagram",
        base_call_meta=call_meta,
    )

    patch: dict = _strip_subagent_messages(dict(output.state_patch) if output else {})
    logger.warning("graph: diagram_node EXIT forced=%s applied=%d", forced, len(patch.get("applied_changes") or []))
    if forced and "forced_finalize" not in patch:
        patch["forced_finalize"] = forced
    return patch


async def researcher_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """LangGraph node: drains researcher.run() iterator. The node already
    injects ``findings`` into ``state_patch``."""
    from app.agents.builtin.general.nodes import researcher
    from app.agents.nodes.base import isolated_state_for_subagent

    enforcer, cm, tool_executor, call_meta = _extract_deps(config)
    tracer = _get_tracer(config)
    logger.warning("graph: researcher_node ENTER")
    iso_state = isolated_state_for_subagent(state)

    output, forced = await _drain_with_tracing(
        node_run=lambda meta: researcher.run(
            iso_state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=tool_executor,
            call_metadata_base=meta,
        ),
        tracer=tracer,
        span_name="researcher",
        base_call_meta=call_meta,
    )

    patch: dict = _strip_subagent_messages(dict(output.state_patch) if output else {})
    logger.warning(
        "graph: researcher_node EXIT forced=%s findings=%s",
        forced,
        bool(patch.get("findings")),
    )
    if forced and "forced_finalize" not in patch:
        patch["forced_finalize"] = forced
    return patch


async def critic_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:
    """LangGraph node: drains critic.run() iterator. The node already
    injects the parsed Critique into ``state_patch['critique']``.

    Iteration counter:
      * If the critic verdict is REVISE and the current iteration is below
        MAX_CRITIQUE_LOOPS, increment iteration so that the next critic pass
        observes the bumped value (and so the routing function can compare).
        The conditional edge :func:`_critic_routes_next` reads ``iteration``
        *before* the increment is observable on the next pass — i.e. the
        increment we apply here is the count of *completed* critic loops.
    """
    from app.agents.builtin.general.nodes import critic
    from app.agents.nodes.base import isolated_state_for_subagent

    enforcer, cm, tool_executor, call_meta = _extract_deps(config)
    tracer = _get_tracer(config)
    logger.warning("graph: critic_node ENTER")
    iso_state = isolated_state_for_subagent(state)

    output, forced = await _drain_with_tracing(
        node_run=lambda meta: critic.run(
            iso_state,
            enforcer=enforcer,
            context_manager=cm,
            tool_executor=tool_executor,
            call_metadata_base=meta,
        ),
        tracer=tracer,
        span_name="critic",
        base_call_meta=call_meta,
    )

    patch: dict = _strip_subagent_messages(dict(output.state_patch) if output else {})

    # Bump iteration when this critic pass produced a REVISE verdict — that's
    # the counter the routing function checks against MAX_CRITIQUE_LOOPS.
    critique = patch.get("critique") if "critique" in patch else state.get("critique")
    if critique is not None:
        verdict = (
            critique.verdict
            if hasattr(critique, "verdict")
            else (critique.get("verdict") if isinstance(critique, dict) else None)
        )
        if verdict == "REVISE":
            current = state.get("iteration") or 0
            patch["iteration"] = current + 1

    if forced and "forced_finalize" not in patch:
        patch["forced_finalize"] = forced
    logger.warning(
        "graph: critic_node EXIT forced=%s verdict=%s",
        forced,
        getattr(patch.get("critique"), "verdict", None)
        if not isinstance(patch.get("critique"), dict)
        else (patch.get("critique") or {}).get("verdict"),
    )
    return patch


async def finalize_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict:  # noqa: ARG001
    """LangGraph node: synchronously builds the final assistant markdown via
    :func:`finalize.build_final_message` and returns it as a state patch.

    Preserves an existing ``final_message`` set upstream (e.g. by the
    supervisor's casual-chat fallback or the explicit finalize tool) so we
    don't overwrite a real reply with the synthetic "No changes were applied"
    summary.
    """
    from app.agents.builtin.general.nodes import finalize as fn

    existing = state.get("final_message")
    if existing:
        logger.warning("graph: finalize_node — preserving existing final_message")
        return {}
    msg = fn.build_final_message(state)
    logger.warning("graph: finalize_node EXIT len=%d", len(msg or ""))
    return {"final_message": msg}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build() -> CompiledStateGraph:
    """Build and compile the general agent graph.

    Edges:
      * ``START → supervisor``
      * ``supervisor →`` conditional: planner | diagram | researcher | critic | finalize
      * ``planner → diagram``
      * ``diagram → supervisor``
      * ``researcher → supervisor``
      * ``critic →`` conditional: planner (REVISE & iter < MAX) | finalize (else)
      * ``finalize → END``

    Compiled with ``checkpointer=None`` — persistence is owned by
    ``agent_chat_session`` (replay on resume from ``state['messages']``).
    """
    from langgraph.graph import END, START, StateGraph

    builder: StateGraph = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("planner", planner_node)
    builder.add_node("diagram", diagram_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("critic", critic_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        _supervisor_routes_next,
        {
            "planner": "planner",
            "diagram": "diagram",
            "researcher": "researcher",
            "critic": "critic",
            "finalize": "finalize",
        },
    )

    # Static post-node edges.
    builder.add_edge("planner", "diagram")
    builder.add_edge("diagram", "supervisor")
    builder.add_edge("researcher", "supervisor")

    builder.add_conditional_edges(
        "critic",
        _critic_routes_next,
        {
            "planner": "planner",
            "finalize": "finalize",
        },
    )

    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=None)


# ---------------------------------------------------------------------------
# Descriptor
# ---------------------------------------------------------------------------


def get_descriptor() -> AgentDescriptor:
    """Return the AgentDescriptor for the general agent.

    Surfaces: ``chat_bubble`` + ``a2a``.
    Modes: ``full`` + ``read_only``.
    Required scope: ``agents:invoke``.
    Default budget: $1.00 / per_invocation, turn limit 200, streaming on.
    """
    return AgentDescriptor(
        id="general",
        name="General Architect",
        description=(
            "Multi-step architecture assistant. Plans, mutates, researches, "
            "and self-critiques workspace C4 models. Used as the default "
            "chat-bubble agent and over A2A for delegated work."
        ),
        schema_version="v1",
        graph=build(),
        surfaces=frozenset({"chat_bubble", "a2a"}),
        allowed_contexts=frozenset({"workspace", "diagram", "object", "none"}),
        supported_modes=("full", "read_only"),
        required_scope="agents:invoke",
        tools_overview=(
            "search_existing_objects",
            "create_object",
            "create_connection",
            "create_diagram",
            "place_on_diagram",
            "fork_diagram_to_draft",
            "delegate_to_planner",
            "delegate_to_diagram",
            "delegate_to_researcher",
            "delegate_to_critic",
        ),
        default_turn_limit=200,
        default_budget_usd=Decimal("1.00"),
        default_budget_scope="per_invocation",
        streaming=True,
    )


__all__ = [
    "MAX_TOTAL_STEPS",
    "MAX_CRITIQUE_LOOPS",
    "build",
    "get_descriptor",
    "supervisor_node",
    "planner_node",
    "diagram_node",
    "researcher_node",
    "critic_node",
    "finalize_node",
    "_supervisor_routes_next",
    "_critic_routes_next",
    "_planner_routes_next",
    "_diagram_routes_next",
    "_researcher_routes_next",
]
