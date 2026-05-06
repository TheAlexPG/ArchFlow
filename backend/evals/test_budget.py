"""Budget eval suite — deterministic, no LLM calls.

Tests LimitsEnforcer for:
  - Pre-flight budget check raises BudgetExhausted when projected cost > budget.
  - Pre-flight allows calls within budget.
  - can_delegate scope behaviour.
  - Turn-limit health-check: progressing extends, stuck raises.
  - Hard cap after max_health_check_extensions.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.errors import BudgetExhausted, TurnLimitReached
from app.agents.limits import (
    HealthCheckResult,
    LimitsEnforcer,
    RuntimeCounters,
    RuntimeLimits,
)
from app.agents.llm import LLMCallMetadata, LLMResult
from app.agents.pricing import ModelPricing

GOLDEN = json.loads((Path(__file__).parent / "golden" / "budget.json").read_text())

_DELEGATE_CASES = [c for c in GOLDEN if "expected_can_delegate" in c]
_HEALTH_CASES = [
    c for c in GOLDEN if "health_check_verdict" in c or "health_check_count" in c
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


def _make_pricing(in_per_m: str = "1.00", out_per_m: str = "2.00") -> ModelPricing:
    return ModelPricing(
        model_id="openai/gpt-4o-mini",
        provider="openai",
        input_per_million=Decimal(in_per_m),
        output_per_million=Decimal(out_per_m),
        source="litellm_builtin",
    )


def _make_llm_result(cost: str | None = "0.01") -> LLMResult:
    return LLMResult(
        text="ok",
        tool_calls=None,
        finish_reason="stop",
        tokens_in=10,
        tokens_out=10,
        cost_usd=Decimal(cost) if cost is not None else None,
        raw=MagicMock(),
    )


def _make_enforcer(
    *,
    turns_used: int = 0,
    cost_usd: str = "0.00",
    budget_usd: str = "1.00",
    turn_limit: int = 200,
    turn_extension: int = 50,
    budget_scope: str = "per_invocation",
    health_check_count: int = 0,
    max_health_check_extensions: int = 3,
    active_turn_limit: int | None = None,
) -> tuple[LimitsEnforcer, MagicMock]:
    limits = RuntimeLimits(
        turn_limit=turn_limit,
        turn_extension=turn_extension,
        max_health_check_extensions=max_health_check_extensions,
        budget_usd=Decimal(budget_usd),
        budget_scope=budget_scope,  # type: ignore[arg-type]
    )
    counters = RuntimeCounters(
        turns_used=turns_used,
        cost_usd=Decimal(cost_usd),
        health_check_count=health_check_count,
    )
    if active_turn_limit is not None:
        counters.active_turn_limit = active_turn_limit
    else:
        counters.active_turn_limit = turn_limit

    mock_llm = MagicMock()
    mock_llm.model = "openai/gpt-4o-mini"
    mock_llm.count_tokens = MagicMock(return_value=100)
    mock_llm.context_window = MagicMock(return_value=200_000)

    mock_db = MagicMock()

    enforcer = LimitsEnforcer(
        limits=limits,
        counters=counters,
        llm=mock_llm,
        db=mock_db,
        workspace_id=uuid4(),
        agent_id="general",
    )
    return enforcer, mock_llm


# ---------------------------------------------------------------------------
# Budget pre-flight cases
# ---------------------------------------------------------------------------


def _is_budget_preflight_case(c: dict) -> bool:
    return (
        "expected_exception" in c
        and "health_check_verdict" not in c
        and "health_check_count" not in c
        and "expected_can_delegate" not in c
    )


@pytest.mark.parametrize(
    "case",
    [c for c in GOLDEN if _is_budget_preflight_case(c)],
    ids=lambda c: c["id"],
)
@pytest.mark.asyncio
async def test_budget_preflight(case: dict) -> None:
    estimated_next = Decimal(str(case.get("estimated_next_cost", "0.10")))
    # We override get_pricing to return our pricing mock that gives estimated_next directly.

    enforcer, mock_llm = _make_enforcer(
        turns_used=case.get("turns_used", 0),
        cost_usd=str(case.get("cost_usd_used", "0.00")),
        budget_usd=str(case.get("budget_usd", "1.00")),
        turn_limit=case.get("turn_limit", 200),
    )

    messages = [{"role": "user", "content": "hello"}]
    meta = _make_call_meta()

    # Patch get_pricing so we control the estimated next cost.
    mock_pricing = MagicMock(spec=ModelPricing)
    mock_pricing.estimate_cost = MagicMock(return_value=estimated_next)

    expected_exc = case.get("expected_exception")

    with patch("app.agents.limits.get_pricing", new=AsyncMock(return_value=mock_pricing)):
        if expected_exc == "BudgetExhausted":
            with pytest.raises(BudgetExhausted):
                await enforcer._enforce_pre_flight(
                    messages=messages,
                    tools=None,
                    metadata=meta,
                    model_override=None,
                )
        else:
            # Should not raise.
            await enforcer._enforce_pre_flight(
                messages=messages,
                tools=None,
                metadata=meta,
                model_override=None,
            )


# ---------------------------------------------------------------------------
# can_delegate cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _DELEGATE_CASES, ids=lambda c: c["id"])
def test_can_delegate(case: dict) -> None:
    enforcer, _ = _make_enforcer(
        cost_usd=str(case["cost_usd_used"]),
        budget_usd=str(case["budget_usd"]),
        budget_scope=case["budget_scope"],
    )
    result = enforcer.can_delegate(agent_id="sub-agent")
    assert result == case["expected_can_delegate"], (
        f"[{case['id']}] Expected can_delegate={case['expected_can_delegate']}, got {result}"
    )


# ---------------------------------------------------------------------------
# Health-check escalation cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", _HEALTH_CASES, ids=lambda c: c["id"])
@pytest.mark.asyncio
async def test_health_check_escalation(case: dict) -> None:
    turns = case.get("turns_used", 10)
    turn_limit = case.get("turn_limit", 10)
    turn_extension = case.get("turn_extension", 5)
    hc_count = case.get("health_check_count", 0)
    max_ext = case.get("max_health_check_extensions", 3)
    verdict = case.get("health_check_verdict", "progressing")
    expected_exc = case.get("expected_exception")

    enforcer, mock_llm = _make_enforcer(
        turns_used=turns,
        turn_limit=turn_limit,
        turn_extension=turn_extension,
        health_check_count=hc_count,
        max_health_check_extensions=max_ext,
        active_turn_limit=turn_limit,
    )

    messages = [{"role": "user", "content": "keep going"}]
    meta = _make_call_meta()

    # Stub _run_health_check so we don't call a real LLM.
    health_result = HealthCheckResult(
        verdict=verdict,
        reason="test verdict",
        should_extend=(verdict == "progressing"),
    )

    with patch.object(enforcer, "_run_health_check", new=AsyncMock(return_value=health_result)):
        if expected_exc == "TurnLimitReached":
            with pytest.raises(TurnLimitReached):
                await enforcer._handle_turn_limit_reached(messages=messages, metadata=meta)
        else:
            await enforcer._handle_turn_limit_reached(messages=messages, metadata=meta)
            expected_limit = case.get("expected_active_turn_limit_after")
            if expected_limit is not None:
                assert enforcer.counters.active_turn_limit == expected_limit, (
                    f"[{case['id']}] Expected active_turn_limit={expected_limit}, "
                    f"got {enforcer.counters.active_turn_limit}"
                )
