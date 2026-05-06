"""Supervisor-only reasoning tools.

These have no ACL checks (internal-only) and do not go to a service.
They mutate AgentState directly via state_patch in the result — the runtime
intercepts specific ``action`` values to update state.scratchpad and to drive
graph routing (delegate_to_* / finalize).

Spec: §4.6 Reasoning tools.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.tools.base import Tool, ToolContext, tool

# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class WriteScratchpadInput(BaseModel):
    """Input for write_scratchpad tool."""

    content: str = Field(..., max_length=10000)  # Full replacement markdown content


class ReadScratchpadInput(BaseModel):
    """Input for read_scratchpad tool (no parameters required)."""

    pass


class DelegateToPlannerInput(BaseModel):
    """Input for delegate_to_planner tool."""

    reason: str
    focus: str


class DelegateToDiagramInput(BaseModel):
    """Input for delegate_to_diagram tool."""

    action_hint: str


class DelegateToResearcherInput(BaseModel):
    """Input for delegate_to_researcher tool."""

    question: str


class DelegateToCriticInput(BaseModel):
    """Input for delegate_to_critic tool (no extra parameters required)."""

    pass


class FinalizeInput(BaseModel):
    """Input for finalize tool."""

    message: str | None = None


# ---------------------------------------------------------------------------
# Scratchpad tools
# ---------------------------------------------------------------------------


@tool(
    name="write_scratchpad",
    description="Replace the supervisor's working notes (markdown). Use as a TODO list.",
    input_schema=WriteScratchpadInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def write_scratchpad(args: WriteScratchpadInput, ctx: ToolContext) -> dict:
    """Return {action: 'scratchpad.written', content: args.content}.

    The runtime intercepts this and copies content into state.scratchpad.
    """
    return {
        "action": "scratchpad.written",
        "content": args.content,
    }


@tool(
    name="read_scratchpad",
    description=(
        "Return the current scratchpad."
        " Usually rendered automatically; prefer reading inline."
    ),
    input_schema=ReadScratchpadInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:read",
    mutating=False,
)
async def read_scratchpad(args: ReadScratchpadInput, ctx: ToolContext) -> dict:
    """Return the current scratchpad content.

    Phase 1 limitation: ctx does not carry direct state access, so we return
    a placeholder. The runtime will route this differently in Phase 2.
    """
    return {
        "action": "scratchpad.read",
        "scratchpad": "",
    }


# ---------------------------------------------------------------------------
# Delegation tools (terminating tool calls — graph router reads the action)
# ---------------------------------------------------------------------------


@tool(
    name="delegate_to_planner",
    description="Hand off complex multi-step tasks to the Planner.",
    input_schema=DelegateToPlannerInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:invoke",
    mutating=False,
)
async def delegate_to_planner(args: DelegateToPlannerInput, ctx: ToolContext) -> dict:
    """Return {action: 'delegate.planner', reason: ..., focus: ...}.

    Routing is handled by the LangGraph supervisor edge.
    """
    return {
        "action": "delegate.planner",
        "reason": args.reason,
        "focus": args.focus,
    }


@tool(
    name="delegate_to_diagram",
    description="Hand off diagram creation or mutation tasks to the Diagram agent.",
    input_schema=DelegateToDiagramInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:invoke",
    mutating=False,
)
async def delegate_to_diagram(args: DelegateToDiagramInput, ctx: ToolContext) -> dict:
    """Return {action: 'delegate.diagram', action_hint: ...}.

    Routing is handled by the LangGraph supervisor edge.
    """
    return {
        "action": "delegate.diagram",
        "action_hint": args.action_hint,
    }


@tool(
    name="delegate_to_researcher",
    description="Hand off research or information-retrieval tasks to the Researcher agent.",
    input_schema=DelegateToResearcherInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:invoke",
    mutating=False,
)
async def delegate_to_researcher(args: DelegateToResearcherInput, ctx: ToolContext) -> dict:
    """Return {action: 'delegate.researcher', question: ...}.

    Routing is handled by the LangGraph supervisor edge.
    """
    return {
        "action": "delegate.researcher",
        "question": args.question,
    }


@tool(
    name="delegate_to_critic",
    description="Ask the Critic agent to review the current plan or result.",
    input_schema=DelegateToCriticInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:invoke",
    mutating=False,
)
async def delegate_to_critic(args: DelegateToCriticInput, ctx: ToolContext) -> dict:
    """Return {action: 'delegate.critic'}.

    Routing is handled by the LangGraph supervisor edge.
    """
    return {
        "action": "delegate.critic",
    }


@tool(
    name="finalize",
    description="End this turn and return the final message to the user.",
    input_schema=FinalizeInput,
    permission="",
    permission_target="workspace",
    required_scope="agents:invoke",
    mutating=False,
)
async def finalize(args: FinalizeInput, ctx: ToolContext) -> dict:
    """Return {action: 'finalize', message: ...}.

    The runtime terminates the current turn upon seeing this action.
    """
    return {
        "action": "finalize",
        "message": args.message,
    }


# ---------------------------------------------------------------------------
# Uppercase aliases for backward-compat imports (these are the Tool instances
# returned by the @tool decorator — already registered in the tool registry).
# ---------------------------------------------------------------------------

WRITE_SCRATCHPAD: Tool = write_scratchpad
READ_SCRATCHPAD: Tool = read_scratchpad
DELEGATE_TO_PLANNER: Tool = delegate_to_planner
DELEGATE_TO_DIAGRAM: Tool = delegate_to_diagram
DELEGATE_TO_RESEARCHER: Tool = delegate_to_researcher
DELEGATE_TO_CRITIC: Tool = delegate_to_critic
FINALIZE: Tool = finalize
