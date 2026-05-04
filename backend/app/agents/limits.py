"""
RuntimeLimits + LimitsEnforcer — turn / budget caps + health-check escalation.

The enforcer wraps an :class:`~app.agents.llm.LLMClient` and adds:

  * **Pre-flight budget check** — refuses calls that would overshoot
    ``budget_usd`` for the active scope (per-invocation or per-request).
  * **Pre-flight turn check** — when the agent reaches ``active_turn_limit`` it
    runs a cheap health-check LLM call; ``progressing`` extends the limit by
    ``turn_extension`` (up to ``max_health_check_extensions`` total),
    ``stuck`` raises :class:`~app.agents.errors.TurnLimitReached`.
  * **Post-call accounting** — increments ``turns_used`` and folds
    ``LLMResult.cost_usd`` into ``cost_usd``; when the model returned no cost
    it logs a warning rather than failing.
  * **Budget warning latch** — when usage crosses ``warn_at_fraction`` of the
    budget the enforcer exposes a one-shot ``(used, limit)`` tuple via
    ``budget_warning_pending`` / ``consume_budget_warning`` so the AgentRuntime
    can emit the SSE ``budget_warning`` event without us coupling to the SSE
    layer here.

The enforcer keeps a reference to a single :class:`RuntimeCounters`. Whether
that instance tracks one node activation (``per_invocation``) or the whole
chat turn (``per_request``) is the caller's choice — see
:meth:`LimitsEnforcer.can_delegate` for how the scope changes pre-delegation
behaviour.

Counters live in-process for the duration of an invocation/request. Persisting
them across requests is not in scope (AgentRuntime rebuilds them each turn).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.errors import AgentError, BudgetExhausted, TurnLimitReached
from app.agents.llm import LLMCallMetadata, LLMClient, LLMResult
from app.agents.pricing import get_pricing


class _HealthCheckResponse(BaseModel):
    """Pydantic shape for the health-check LLM's JSON response.

    Used to drive the ``response_format={"type": "json_schema", ...}``
    constrained-decoding path on LM Studio / OpenAI. The dataclass
    :class:`HealthCheckResult` keeps the runtime-internal shape; this
    model only exists to derive a JSON Schema for the API call.
    """

    verdict: Literal["progressing", "stuck"]
    reason: str = Field(default="", max_length=500)
    should_extend: bool | None = None


def _json_schema_response_format(model: type[BaseModel]) -> dict:
    """Build OpenAI-style ``json_schema`` response_format from a Pydantic model.

    Same shape works on OpenAI, LM Studio, and other OpenAI-compat servers
    that support structured outputs. We do not pass ``strict: True`` because
    Pydantic v2's auto-generated schemas don't always carry
    ``additionalProperties: false`` at every nested level — the parse
    fallback in the caller handles minor schema drift.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "schema": model.model_json_schema(),
        },
    }

logger = logging.getLogger(__name__)


BudgetScope = Literal["per_invocation", "per_request"]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RuntimeLimits:
    """Configuration caps for a single agent invocation."""

    turn_limit: int = 200
    turn_extension: int = 50
    max_health_check_extensions: int = 3  # hard cap on health-check escalations
    budget_usd: Decimal = Decimal("1.00")
    budget_scope: BudgetScope = "per_invocation"
    on_budget_exhausted: Literal["summarize_and_finalize", "fail"] = "summarize_and_finalize"
    health_check_model: str = "openai/gpt-4o-mini"


@dataclass
class RuntimeCounters:
    """Mutable counters tracking resource consumption during an invocation."""

    turns_used: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    last_health_check_at_turn: int = 0
    health_check_count: int = 0
    # Mutated by health-check escalation. 0 means "not yet primed";
    # LimitsEnforcer initialises it from limits.turn_limit on construction.
    active_turn_limit: int = 0
    # Aggregated token usage across every LLM call routed through the enforcer
    # in this invocation (supervisor + researcher + planner + diagram + critic
    # + finalize + health-checks). Reported on the terminal ``usage`` SSE event
    # so the chat footer reflects the whole turn, not just the last call.
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class HealthCheckResult:
    """Verdict from the cheap health-check call."""

    verdict: Literal["progressing", "stuck"]
    reason: str
    should_extend: bool  # echoes verdict-decision, but explicit for callers


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BudgetWarning(AgentError):  # noqa: N818
    """Raised informationally when usage crosses the warn_at_fraction threshold.

    Currently the enforcer surfaces the warning via
    :attr:`LimitsEnforcer.budget_warning_pending` rather than raising — this
    class is exported for callers that prefer an exception-style API or want
    to construct an ``SSE`` payload from one place.
    """

    def __init__(self, scope: str, used: Decimal, limit: Decimal):
        self.scope = scope
        self.used = used
        self.limit = limit
        super().__init__(f"Budget warning: {used}/{limit} on {scope}")


# ---------------------------------------------------------------------------
# Enforcer
# ---------------------------------------------------------------------------


# Health-check prompt — keep it short. Goal is anti-loop detection, not deep
# reasoning. Budget for the input is < 500 tokens.
_HEALTH_CHECK_SYSTEM_PROMPT = (
    "You are an agent supervisor. Decide whether the agent is making progress "
    "toward the user's goal or is stuck in a loop / spinning on the same task. "
    "Respond with a JSON object exactly matching this shape: "
    '{"verdict": "progressing" | "stuck", "reason": "<one short sentence>", '
    '"should_extend": true | false}. '
    'Set "progressing" + should_extend=true only when there is clear forward '
    "motion on the user's stated goal."
)

# Truncation guards for the compact health-check prompt.
_HEALTH_CHECK_MSG_PREVIEW_CHARS = 200
_HEALTH_CHECK_MSG_TAIL = 6
_HEALTH_CHECK_TOOL_TAIL = 4


class LimitsEnforcer:
    """Wraps :class:`LLMClient` with budget + turn-limit enforcement.

    See module docstring for the full responsibility split.
    """

    def __init__(
        self,
        *,
        limits: RuntimeLimits,
        counters: RuntimeCounters,
        llm: LLMClient,
        db: AsyncSession,
        workspace_id: UUID,
        agent_id: str,
        warn_at_fraction: float = 0.85,
    ) -> None:
        self.limits = limits
        self.counters = counters
        self.llm = llm
        self.db = db
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.warn_at_fraction = warn_at_fraction

        # Prime the dynamic turn limit on first construction (or rehydration).
        if self.counters.active_turn_limit <= 0:
            self.counters.active_turn_limit = self.limits.turn_limit

        # Latch state for the one-shot budget warning.
        self._budget_warning_pending: tuple[Decimal, Decimal] | None = None
        self._budget_warning_emitted: bool = False

    # ---- public surface --------------------------------------------------

    @property
    def budget_warning_pending(self) -> tuple[Decimal, Decimal] | None:
        """Return ``(used, limit)`` if a warning is pending, else ``None``.

        Reading this property does NOT clear the latch — use
        :meth:`consume_budget_warning` to read-and-clear.
        """
        return self._budget_warning_pending

    def consume_budget_warning(self) -> tuple[Decimal, Decimal] | None:
        """Read & clear the pending warning (caller emits SSE)."""
        pending = self._budget_warning_pending
        self._budget_warning_pending = None
        return pending

    def can_delegate(
        self,
        *,
        agent_id: str,  # noqa: ARG002 — accepted for parity with future per-agent rules
        requested_remaining: Decimal | None = None,  # noqa: ARG002 — reserved
    ) -> bool:
        """Pre-delegation budget check.

        For ``per_request`` scope: returns ``False`` once
        ``cost_usd >= budget_usd`` so the supervisor surfaces
        ``agent_budget_exhausted`` instead of paying for another sub-agent
        spin-up. For ``per_invocation`` scope each delegation gets its own
        fresh budget, so this is always allowed at the gate.
        """
        if self.limits.budget_scope == "per_request":
            return self.counters.cost_usd < self.limits.budget_usd
        return True

    # ---- main entry point ------------------------------------------------

    async def acompletion(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        response_format: dict | None = None,
        metadata: LLMCallMetadata,
        model_override: str | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        """Wrap :meth:`LLMClient.acompletion` with pre-flight + post-call accounting.

        Sequence:
          1. Pre-flight: turn check (may run health-check + extend, or raise),
             budget check (may raise), warning latch.
          2. Forward to the inner LLMClient.
          3. Post-call: ``turns_used += 1``; fold ``cost_usd`` if known.
        """
        await self._enforce_pre_flight(
            messages=messages,
            tools=tools,
            metadata=metadata,
            model_override=model_override,
        )

        result = await self.llm.acompletion(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            metadata=metadata,
            model_override=model_override,
            **kwargs,
        )

        self.counters.turns_used += 1

        # Aggregate tokens regardless of whether pricing is resolvable —
        # OpenRouter/free-tier models often skip the price catalog yet still
        # report ``usage.prompt_tokens/completion_tokens``. The chat footer
        # needs these even when ``cost_usd`` is None.
        self.counters.tokens_in += int(result.tokens_in or 0)
        self.counters.tokens_out += int(result.tokens_out or 0)

        if result.cost_usd is not None:
            self.counters.cost_usd += result.cost_usd
            self._maybe_latch_budget_warning()
        else:
            logger.warning(
                "cost not resolvable for model %s (agent=%s); budget not incremented",
                model_override or self.llm.model,
                self.agent_id,
            )

        return result

    # ---- pre-flight ------------------------------------------------------

    async def _enforce_pre_flight(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        metadata: LLMCallMetadata,
        model_override: str | None,
    ) -> None:
        """Run turn + budget checks before letting the call go through."""
        # ---- turn check (may extend or raise) ----
        if self.counters.turns_used >= self.counters.active_turn_limit:
            await self._handle_turn_limit_reached(
                messages=messages,
                metadata=metadata,
            )

        # ---- budget check ----
        target_model = model_override or self.llm.model
        estimated_next = await self._estimate_next_call_cost(
            messages=messages, tools=tools, model=target_model
        )

        projected = self.counters.cost_usd + estimated_next
        if projected > self.limits.budget_usd:
            raise BudgetExhausted(
                f"Budget {self.limits.budget_usd} would be exceeded "
                f"(used={self.counters.cost_usd}, "
                f"estimated_next={estimated_next}, "
                f"scope={self.limits.budget_scope})"
            )

        # ---- warning latch (set once, on first crossing) ----
        self._maybe_latch_budget_warning()

    def _maybe_latch_budget_warning(self) -> None:
        """Set the one-shot warning latch when usage crosses ``warn_at_fraction``."""
        if self._budget_warning_emitted:
            return
        if self.limits.budget_usd <= 0:
            return
        threshold = self.limits.budget_usd * Decimal(str(self.warn_at_fraction))
        if self.counters.cost_usd >= threshold:
            self._budget_warning_pending = (
                self.counters.cost_usd,
                self.limits.budget_usd,
            )
            self._budget_warning_emitted = True

    async def _estimate_next_call_cost(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None,
        model: str,
    ) -> Decimal:
        """Return an estimated USD cost for the upcoming call.

        If pricing is not resolvable, returns ``Decimal("0")`` so we don't
        block calls when we cannot estimate (post-call accounting still
        applies if the provider returns a cost). This mirrors the spec's
        layered pricing fallback: "pricing unknown → budget tracking
        disabled".
        """
        pricing = await get_pricing(self.db, self.workspace_id, model)
        if pricing is None:
            return Decimal("0")

        try:
            tokens_in = self.llm.count_tokens(messages, tools=tools)
        except Exception:  # pragma: no cover — defensive
            tokens_in = 0

        # Estimate output tokens conservatively at ~25% of the prompt — this is
        # a heuristic to detect "this single call will overshoot" rather than a
        # precise prediction; actual cost replaces it post-call.
        tokens_out_estimate = max(256, tokens_in // 4)
        return pricing.estimate_cost(tokens_in, tokens_out_estimate)

    # ---- health-check escalation ----------------------------------------

    async def _handle_turn_limit_reached(
        self,
        *,
        messages: list[dict],
        metadata: LLMCallMetadata,
    ) -> None:
        """Run health-check; either extend the turn budget or raise."""
        if self.counters.health_check_count >= self.limits.max_health_check_extensions:
            raise TurnLimitReached(
                f"Turn limit {self.limits.turn_limit} reached and "
                f"max_health_check_extensions={self.limits.max_health_check_extensions} "
                f"already used"
            )

        verdict = await self._run_health_check(messages=messages, call_metadata=metadata)
        if verdict.should_extend:
            self.counters.active_turn_limit = (
                self.counters.turns_used + self.limits.turn_extension
            )
            self.counters.health_check_count += 1
            self.counters.last_health_check_at_turn = self.counters.turns_used
            return

        raise TurnLimitReached(
            f"Turn limit reached and health-check verdict='{verdict.verdict}': "
            f"{verdict.reason}"
        )

    async def _run_health_check(
        self,
        *,
        messages: list[dict],
        call_metadata: LLMCallMetadata,
    ) -> HealthCheckResult:
        """Cheap LLM call to evaluate whether the agent is making progress.

        We deliberately:
          * Use the *raw* :class:`LLMClient` (not ``self.acompletion``) — we
            don't want the health-check itself to recurse through pre-flight
            checks.
          * Account for the cost in :attr:`counters.cost_usd` so the health-
            check eats the same budget as the agent it is policing.
          * Use ``response_format={"type": "json_schema", ...}`` derived from
            :class:`_HealthCheckResponse` so the server constrains decoding
            to a known shape. Fall back to ``text`` if the provider rejects
            the schema; a manual JSON parse below handles either case.
            (``json_object`` is not universally supported — LM Studio's qwen
            rejects it with HTTP 400.)
        """
        compact_prompt = self._build_health_check_prompt(messages)

        response_format_schema = _json_schema_response_format(_HealthCheckResponse)
        try:
            result = await self.llm.acompletion(
                compact_prompt,
                response_format=response_format_schema,
                metadata=call_metadata,
                model_override=self.limits.health_check_model,
            )
        except Exception as schema_exc:
            logger.warning(
                "health-check json_schema rejected (%s); retrying as text",
                schema_exc,
            )
            try:
                result = await self.llm.acompletion(
                    compact_prompt,
                    response_format={"type": "text"},
                    metadata=call_metadata,
                    model_override=self.limits.health_check_model,
                )
            except Exception as e:  # pragma: no cover — defensive
                # If even the cheap probe fails we treat that as "stuck" —
                # better to terminate than spin further.
                logger.warning(
                    "health-check call failed: %s — defaulting to stuck", e
                )
                return HealthCheckResult(
                    verdict="stuck",
                    reason=f"health-check call failed: {e}",
                    should_extend=False,
                )

        # Account for the health-check's cost + tokens in the same budget.
        self.counters.tokens_in += int(result.tokens_in or 0)
        self.counters.tokens_out += int(result.tokens_out or 0)
        if result.cost_usd is not None:
            self.counters.cost_usd += result.cost_usd

        return self._parse_health_check_response(result.text)

    def _build_health_check_prompt(self, messages: list[dict]) -> list[dict]:
        """Build the compact prompt for the health-check call.

        Includes:
          * the user's initial goal (first user message),
          * the last 6 messages truncated to 200 chars each,
          * the last 4 tool calls extracted from those messages,
          * a short system instruction.
        """
        initial_goal = self._extract_initial_goal(messages)
        recent = self._summarize_recent_messages(messages, _HEALTH_CHECK_MSG_TAIL)
        tool_calls = self._extract_recent_tool_calls(messages, _HEALTH_CHECK_TOOL_TAIL)

        user_payload = {
            "initial_goal": initial_goal,
            "recent_messages": recent,
            "recent_tool_calls": tool_calls,
            "turns_used": self.counters.turns_used,
            "active_turn_limit": self.counters.active_turn_limit,
            "health_check_count": self.counters.health_check_count,
        }

        return [
            {"role": "system", "content": _HEALTH_CHECK_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ]

    @staticmethod
    def _extract_initial_goal(messages: list[dict]) -> str:
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content")
                text = content if isinstance(content, str) else json.dumps(content, default=str)
                return text[:_HEALTH_CHECK_MSG_PREVIEW_CHARS]
        return ""

    @staticmethod
    def _summarize_recent_messages(
        messages: list[dict], n: int
    ) -> list[dict[str, str]]:
        recent = messages[-n:] if len(messages) > n else list(messages)
        out: list[dict[str, str]] = []
        for m in recent:
            content = m.get("content")
            text = content if isinstance(content, str) else json.dumps(content, default=str)
            out.append(
                {
                    "role": str(m.get("role", "")),
                    "content": (text or "")[:_HEALTH_CHECK_MSG_PREVIEW_CHARS],
                }
            )
        return out

    @staticmethod
    def _extract_recent_tool_calls(
        messages: list[dict], n: int
    ) -> list[dict[str, str]]:
        """Walk messages backwards collecting tool calls + their results."""
        results: list[dict[str, str]] = []
        # Map tool_call_id -> result status. Iterate from oldest to newest so we
        # can pair an assistant tool_call with the subsequent tool message; then
        # take the last n.
        result_status_by_id: dict[str, str] = {}
        for m in messages:
            if m.get("role") == "tool":
                tc_id = m.get("tool_call_id") or ""
                content = m.get("content") or ""
                content_str = (
                    content if isinstance(content, str) else json.dumps(content, default=str)
                )
                # Heuristic — if content mentions error/exception, mark error.
                lowered = content_str.lower()
                status = "error" if ("error" in lowered or "exception" in lowered) else "ok"
                if tc_id:
                    result_status_by_id[tc_id] = status

        # Now collect tool calls from assistant messages (preserving order).
        for m in messages:
            if m.get("role") != "assistant":
                continue
            for tc in m.get("tool_calls") or []:
                tc_id = tc.get("id") or ""
                fn = tc.get("function") or {}
                name = fn.get("name") or tc.get("name") or ""
                args = fn.get("arguments") or tc.get("arguments") or ""
                args_str = args if isinstance(args, str) else json.dumps(args, default=str)
                results.append(
                    {
                        "name": str(name),
                        "arguments": args_str[:_HEALTH_CHECK_MSG_PREVIEW_CHARS],
                        "status": result_status_by_id.get(tc_id, "pending"),
                    }
                )

        return results[-n:] if results else []

    @staticmethod
    def _parse_health_check_response(text: str | None) -> HealthCheckResult:
        """Parse the JSON verdict; default to ``stuck`` on any error."""
        if not text:
            return HealthCheckResult(
                verdict="stuck",
                reason="health-check returned empty response",
                should_extend=False,
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return HealthCheckResult(
                verdict="stuck",
                reason="health-check response was not valid JSON",
                should_extend=False,
            )
        verdict = payload.get("verdict")
        reason = str(payload.get("reason") or "")
        # Trust the explicit should_extend flag if present, otherwise derive
        # from the verdict.
        if "should_extend" in payload:
            should_extend = bool(payload.get("should_extend"))
        else:
            should_extend = verdict == "progressing"

        if verdict not in ("progressing", "stuck"):
            return HealthCheckResult(
                verdict="stuck",
                reason=f"unrecognized verdict {verdict!r}",
                should_extend=False,
            )
        # Defensive: never extend on a 'stuck' verdict.
        if verdict == "stuck":
            should_extend = False
        return HealthCheckResult(
            verdict=verdict,
            reason=reason,
            should_extend=should_extend,
        )
