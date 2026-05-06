"""
AgentState TypedDict and supporting Pydantic models (Plan, Critique, Findings, etc.).
These types are shared across all agent nodes and graph implementations.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field  # noqa: I001

# ---------------------------------------------------------------------------
# Supporting Pydantic models
# ---------------------------------------------------------------------------


class ActorRef(BaseModel):
    """Lightweight reference to the invoking actor (user or API key)."""

    actor_id: UUID
    actor_kind: Literal["user", "api_key"]
    workspace_id: UUID


class ChatContext(BaseModel):
    """Frontend-supplied context that scopes the agent invocation."""

    kind: Literal["workspace", "diagram", "object", "none"]
    id: UUID | None = None
    draft_id: UUID | None = None
    parent_diagram_id: UUID | None = None


# ---------------------------------------------------------------------------
# Planner output models
# ---------------------------------------------------------------------------

# Set of planner-allowed action kinds. The diagram-agent tool wrapper
# (task 026/027) is responsible for validating ``args`` against the actual
# tool's Pydantic schema; the planner only emits intent.
PlanActionKind = Literal[
    "search_existing_object",
    "create_object",
    "create_connection",
    "place_on_diagram",
    "move_on_diagram",
    "create_child_diagram",
    "link_object_to_child_diagram",
    "create_child_diagram_for_object",
    "update_object",
    "update_connection",
    "delete_object",
    "delete_connection",
    "auto_layout_diagram",
]


class PlanStep(BaseModel):
    """A single step inside a :class:`Plan` produced by the planner node."""

    index: int = Field(
        ...,
        ge=0,
        description="0-based index used for depends_on references",
    )
    kind: PlanActionKind
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool args (validated later by tool wrapper)",
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="indices of prior steps this depends on",
    )
    rationale: str = Field(..., max_length=500)


class Plan(BaseModel):
    """Structured plan produced by the planner node.

    Validated client-side by the diagram-agent before execution. ``steps``
    is bounded at 40 to keep the planner from emitting unbounded sprawls;
    the planner is instructed to return the *first phase* and note the rest
    in ``goal`` if the work doesn't fit.
    """

    goal: str = Field(..., max_length=500)
    steps: list[PlanStep] = Field(..., min_length=1, max_length=40)
    reuse_findings: list[str] = Field(
        default_factory=list,
        description=(
            "Free-form notes about objects/technologies reused from the workspace "
            "(e.g., 'reuses Postgres id=...')."
        ),
    )

    def topological_order(self) -> list[PlanStep]:
        """Return ``self.steps`` in a valid execution order using Kahn's algorithm.

        Validates that ``depends_on`` references are in-range and that the
        dependency graph is acyclic. Raises :class:`ValueError` on either
        violation.

        Steps are keyed by their ``index`` field, NOT their list position —
        this matches how the LLM is instructed to emit ``depends_on``.
        """
        # Index -> step lookup. The model permits duplicate indices at the
        # schema level (a list[int] is just a list); we explicitly check.
        by_index: dict[int, PlanStep] = {}
        for step in self.steps:
            if step.index in by_index:
                raise ValueError(f"duplicate step index: {step.index}")
            by_index[step.index] = step

        # Validate depends_on references.
        valid_indices = set(by_index)
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in valid_indices:
                    raise ValueError(
                        f"step {step.index}: depends_on references unknown index {dep}"
                    )
                if dep == step.index:
                    raise ValueError(f"step {step.index}: cannot depend on itself")

        # Kahn's algorithm.
        in_degree: dict[int, int] = {idx: 0 for idx in by_index}
        for step in self.steps:
            in_degree[step.index] = len(step.depends_on)

        # Sort by index to make the order deterministic when ties occur.
        ready = sorted(idx for idx, deg in in_degree.items() if deg == 0)
        ordered: list[PlanStep] = []

        # Successor map: for a given index, who depends on it.
        successors: dict[int, list[int]] = {idx: [] for idx in by_index}
        for step in self.steps:
            for dep in step.depends_on:
                successors[dep].append(step.index)

        while ready:
            current = ready.pop(0)
            ordered.append(by_index[current])
            for succ in successors[current]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    # Insert maintaining sort order for determinism.
                    inserted = False
                    for i, existing in enumerate(ready):
                        if succ < existing:
                            ready.insert(i, succ)
                            inserted = True
                            break
                    if not inserted:
                        ready.append(succ)

        if len(ordered) != len(by_index):
            remaining = sorted(set(by_index) - {s.index for s in ordered})
            raise ValueError(
                f"plan has a dependency cycle; unresolved steps: {remaining}"
            )
        return ordered


class Findings(BaseModel):
    """Free-form research findings produced by the researcher node."""

    summary: str
    details: str
    sources: list[str] = []


class Critique(BaseModel):
    """Critic verdict produced by the critic node."""

    verdict: Literal["APPROVE", "REVISE"]
    strengths: list[str] = Field(default_factory=list, max_length=10)
    issues: list[str] = Field(default_factory=list, max_length=10)
    revision_request: str | None = Field(
        None,
        max_length=2000,
        description="Concrete instructions for planner if REVISE",
    )


class ChangeRecord(BaseModel):
    """Record of a single applied mutation (for the applied_changes list)."""

    action: str
    target_type: str
    target_id: UUID
    name: str | None = None
    diagram_id: UUID | None = None
    metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# AgentState — shared LangGraph state TypedDict
# ---------------------------------------------------------------------------

try:
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore[assignment]


class AgentState(TypedDict, total=False):
    """Shared state passed through the LangGraph agent graph."""

    workspace_id: UUID
    session_id: UUID
    actor: Any  # ActorRef placeholder — avoid circular import at graph build time
    chat_context: dict  # ChatContext serialised to dict
    runtime_mode: Literal["full", "read_only"]
    active_draft_id: UUID | None
    messages: list[dict]
    plan: Plan | None
    findings: Findings | None
    pending_changes: list[dict]
    applied_changes: list[dict]
    critique: Critique | None
    iteration: int
    scratchpad: str
    final_message: str | None
    trace_id: str | None
    tokens_in: int
    tokens_out: int
    forced_finalize: str | None
    budget_counters: dict
    # Bumped by the supervisor LangGraph wrapper on every visit so the router
    # can short-circuit runaway delegation loops at MAX_TOTAL_STEPS.
    supervisor_visits: int
    compaction_stage: int
    # Brief from the supervisor's most recent delegate_to_* tool call. Sub-agents
    # (researcher / planner / diagram / critic / repo_researcher) read this so
    # they receive the supervisor's specific instruction, not just the raw user
    # input.
    # Shape: {"kind": "researcher"|"planner"|"diagram"|"critic"|"repo:<slug>",
    #         "instruction": str, "reason": str | None}
    delegate_brief: dict | None
    # Per-turn manifest of repo-linked objects on the active diagram. Populated
    # by ``app.agents.builtin.general.manifest.collect_repo_manifest`` at
    # invocation start. Each entry is a serialized
    # ``app.agents.builtin.general.manifest.RepoLink`` dict (so the state stays
    # JSON-friendly across LangGraph checkpoints).
    repo_manifest: list[dict]
    # Resolved repo context for the active ``repo_researcher`` invocation —
    # populated by the graph wrapper just before ``repo_researcher.run`` is
    # entered. Shape mirrors a ``RepoLink`` minus the manifest-only fields.
    repo_context: dict | None
    # Free-form markdown answer produced by the repo_researcher node — surfaced
    # in the supervisor's history via ``rewrite_subagent_tool_result``.
    repo_response: str | None
