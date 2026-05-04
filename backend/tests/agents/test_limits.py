"""Tests for app/agents/limits.py.

The enforcer wraps an LLMClient. We mock the LLMClient (not litellm) so we
control exactly what cost / text / tool_calls each call returns. Pricing is
also mocked so each test sets up a deterministic ``ModelPricing`` (or None).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
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

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_call_meta() -> LLMCallMetadata:
    return LLMCallMetadata(
        workspace_id=uuid4(),
        agent_id="general",
        session_id=uuid4(),
        actor_id=uuid4(),
        analytics_consent="off",
    )


def _make_pricing(*, in_per_m: str = "1.00", out_per_m: str = "2.00") -> ModelPricing:
    return ModelPricing(
        model_id="openai/gpt-4o-mini",
        provider="openai",
        input_per_million=Decimal(in_per_m),
        output_per_million=Decimal(out_per_m),
        source="litellm_builtin",
    )


def _make_llm_result(
    *,
    text: str = "ok",
    cost_usd: Decimal | None = Decimal("0.01"),
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
) -> LLMResult:
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        tokens_in=10,
        tokens_out=10,
        cost_usd=cost_usd,
        raw=MagicMock(),
    )


def _make_mock_llm(
    *,
    completion_result: LLMResult | None = None,
    completion_results: list[LLMResult] | None = None,
    model: str = "openai/gpt-4o-mini",
    count_tokens_value: int = 100,
) -> MagicMock:
    """Build an LLMClient mock.

    ``completion_results`` (list) wins over ``completion_result`` (single).
    """
    llm = MagicMock()
    llm.model = model
    llm.count_tokens = MagicMock(return_value=count_tokens_value)

    if completion_results is not None:
        llm.acompletion = AsyncMock(side_effect=completion_results)
    else:
        llm.acompletion = AsyncMock(
            return_value=completion_result or _make_llm_result()
        )
    return llm


@pytest.fixture()
def patch_pricing(monkeypatch):
    """Helper to install a mock pricing return value for a test."""

    def _install(pricing: ModelPricing | None) -> AsyncMock:
        mock = AsyncMock(return_value=pricing)
        monkeypatch.setattr("app.agents.limits.get_pricing", mock)
        return mock

    return _install


def _make_enforcer(
    *,
    limits: RuntimeLimits | None = None,
    counters: RuntimeCounters | None = None,
    llm: MagicMock | None = None,
    warn_at_fraction: float = 0.85,
) -> LimitsEnforcer:
    return LimitsEnforcer(
        limits=limits or RuntimeLimits(),
        counters=counters or RuntimeCounters(),
        llm=llm or _make_mock_llm(),
        db=MagicMock(),  # not used directly; pricing mock intercepts
        workspace_id=uuid4(),
        agent_id="general",
        warn_at_fraction=warn_at_fraction,
    )


# ---------------------------------------------------------------------------
# Constructor / defaults
# ---------------------------------------------------------------------------


def test_enforcer_primes_active_turn_limit_from_turn_limit(patch_pricing):
    patch_pricing(_make_pricing())
    counters = RuntimeCounters()
    assert counters.active_turn_limit == 0
    _make_enforcer(counters=counters)
    assert counters.active_turn_limit == 200


def test_enforcer_preserves_active_turn_limit_when_already_set(patch_pricing):
    patch_pricing(_make_pricing())
    counters = RuntimeCounters(active_turn_limit=42)
    _make_enforcer(counters=counters)
    assert counters.active_turn_limit == 42


# ---------------------------------------------------------------------------
# Pre-flight pass under budget
# ---------------------------------------------------------------------------


async def test_acompletion_under_budget_succeeds_and_increments(patch_pricing):
    patch_pricing(_make_pricing())
    counters = RuntimeCounters(cost_usd=Decimal("0.10"), turns_used=5)
    llm = _make_mock_llm(
        completion_result=_make_llm_result(cost_usd=Decimal("0.01"))
    )
    enf = _make_enforcer(counters=counters, llm=llm)

    result = await enf.acompletion(
        [{"role": "user", "content": "hi"}],
        metadata=_make_call_meta(),
    )

    assert result.text == "ok"
    assert counters.turns_used == 6
    assert counters.cost_usd == Decimal("0.11")
    llm.acompletion.assert_awaited_once()


# ---------------------------------------------------------------------------
# BudgetExhausted on overshoot
# ---------------------------------------------------------------------------


async def test_acompletion_raises_budget_exhausted_when_next_overshoots(patch_pricing):
    # Pricing chosen so estimate easily exceeds the headroom.
    pricing = _make_pricing(in_per_m="500000", out_per_m="500000")
    patch_pricing(pricing)
    counters = RuntimeCounters(cost_usd=Decimal("0.99"))
    limits = RuntimeLimits(budget_usd=Decimal("1.00"))
    llm = _make_mock_llm(count_tokens_value=1_000)
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    with pytest.raises(BudgetExhausted) as exc_info:
        await enf.acompletion(
            [{"role": "user", "content": "hi"}],
            metadata=_make_call_meta(),
        )
    msg = str(exc_info.value)
    assert "1.00" in msg
    assert "0.99" in msg
    # The inner LLM was never called.
    llm.acompletion.assert_not_called()
    # Counters not advanced.
    assert counters.turns_used == 0
    assert counters.cost_usd == Decimal("0.99")


# ---------------------------------------------------------------------------
# Budget warning latch at 85%
# ---------------------------------------------------------------------------


async def test_budget_warning_latched_after_crossing_threshold(patch_pricing):
    patch_pricing(_make_pricing())  # cheap pricing → estimate ~= 0
    counters = RuntimeCounters(cost_usd=Decimal("0.50"))
    limits = RuntimeLimits(budget_usd=Decimal("1.00"))
    # First call returns enough cost to push us across 85% threshold.
    llm = _make_mock_llm(
        completion_results=[
            _make_llm_result(cost_usd=Decimal("0.40")),  # → 0.90 > 0.85 threshold
            _make_llm_result(cost_usd=Decimal("0.01")),  # latch should NOT re-fire
        ]
    )
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    # Before any call: no warning pending.
    assert enf.budget_warning_pending is None

    await enf.acompletion(
        [{"role": "user", "content": "hi"}],
        metadata=_make_call_meta(),
    )
    pending = enf.budget_warning_pending
    assert pending is not None
    used, limit = pending
    assert used == Decimal("0.90")
    assert limit == Decimal("1.00")

    # consume_budget_warning returns and clears.
    consumed = enf.consume_budget_warning()
    assert consumed == (Decimal("0.90"), Decimal("1.00"))
    assert enf.budget_warning_pending is None
    assert enf.consume_budget_warning() is None

    # A subsequent call must NOT relatch (one-shot).
    await enf.acompletion(
        [{"role": "user", "content": "again"}],
        metadata=_make_call_meta(),
    )
    assert enf.budget_warning_pending is None


# ---------------------------------------------------------------------------
# Cost not resolvable
# ---------------------------------------------------------------------------


async def test_cost_not_resolvable_does_not_increment_budget(
    patch_pricing, caplog: pytest.LogCaptureFixture
):
    patch_pricing(_make_pricing())
    counters = RuntimeCounters(cost_usd=Decimal("0.10"))
    llm = _make_mock_llm(completion_result=_make_llm_result(cost_usd=None))
    enf = _make_enforcer(counters=counters, llm=llm)

    with caplog.at_level(logging.WARNING, logger="app.agents.limits"):
        await enf.acompletion(
            [{"role": "user", "content": "hi"}],
            metadata=_make_call_meta(),
        )

    # Turn count still ticks
    assert counters.turns_used == 1
    # Budget is unchanged
    assert counters.cost_usd == Decimal("0.10")
    # Warning was logged
    assert any(
        "cost not resolvable" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Health-check escalation: progressing → extend
# ---------------------------------------------------------------------------


async def test_turn_limit_triggers_health_check_progressing_extends(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(turn_limit=10, turn_extension=5)
    counters = RuntimeCounters(turns_used=10, active_turn_limit=10)

    health_check_response = _make_llm_result(
        text=json.dumps(
            {"verdict": "progressing", "reason": "moving forward", "should_extend": True}
        ),
        cost_usd=Decimal("0.001"),
    )
    main_response = _make_llm_result(cost_usd=Decimal("0.01"))

    # 1st call → health-check; 2nd call → the actual completion.
    llm = _make_mock_llm(completion_results=[health_check_response, main_response])
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    result = await enf.acompletion(
        [{"role": "user", "content": "do thing"}],
        metadata=_make_call_meta(),
    )
    assert result is main_response

    # Health-check extended the limit by turn_extension.
    assert counters.health_check_count == 1
    assert counters.last_health_check_at_turn == 10
    assert counters.active_turn_limit == 15
    # turns_used incremented once for the main call (health-check uses raw llm).
    assert counters.turns_used == 11
    # Cost incremented for both calls.
    assert counters.cost_usd == Decimal("0.011")


# ---------------------------------------------------------------------------
# Health-check escalation: stuck → TurnLimitReached
# ---------------------------------------------------------------------------


async def test_health_check_stuck_raises_turn_limit_reached(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(turn_limit=10, turn_extension=5)
    counters = RuntimeCounters(turns_used=10, active_turn_limit=10)
    health_check_response = _make_llm_result(
        text=json.dumps(
            {"verdict": "stuck", "reason": "looping on same tool", "should_extend": False}
        ),
        cost_usd=Decimal("0.001"),
    )
    llm = _make_mock_llm(completion_results=[health_check_response])
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    with pytest.raises(TurnLimitReached) as exc_info:
        await enf.acompletion(
            [{"role": "user", "content": "do thing"}],
            metadata=_make_call_meta(),
        )
    assert "stuck" in str(exc_info.value)
    # Turn limit unchanged.
    assert counters.active_turn_limit == 10
    assert counters.health_check_count == 0


# ---------------------------------------------------------------------------
# Hard cap on extensions
# ---------------------------------------------------------------------------


async def test_hard_cap_on_extensions_raises_even_when_progressing(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(
        turn_limit=10, turn_extension=5, max_health_check_extensions=3
    )
    # Already used 3 extensions; turns_used at the now-extended limit.
    counters = RuntimeCounters(
        turns_used=25,
        active_turn_limit=25,
        health_check_count=3,
    )
    # If we ever hit acompletion the test should fail — health-check should
    # not even run because we are at the hard cap.
    llm = _make_mock_llm(
        completion_result=_make_llm_result(
            text=json.dumps(
                {"verdict": "progressing", "reason": "still moving", "should_extend": True}
            )
        )
    )
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    with pytest.raises(TurnLimitReached) as exc_info:
        await enf.acompletion(
            [{"role": "user", "content": "do thing"}],
            metadata=_make_call_meta(),
        )
    assert "max_health_check_extensions" in str(exc_info.value)
    # No LLM call made (we short-circuited before the health-check).
    llm.acompletion.assert_not_called()


# ---------------------------------------------------------------------------
# can_delegate
# ---------------------------------------------------------------------------


def test_can_delegate_per_request_blocks_when_exhausted(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(budget_scope="per_request", budget_usd=Decimal("1.00"))
    counters = RuntimeCounters(cost_usd=Decimal("0.99"))
    enf = _make_enforcer(limits=limits, counters=counters)
    assert enf.can_delegate(agent_id="researcher") is True

    counters.cost_usd = Decimal("1.00")
    assert enf.can_delegate(agent_id="researcher") is False


def test_can_delegate_per_request_allows_under_budget(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(budget_scope="per_request", budget_usd=Decimal("1.00"))
    counters = RuntimeCounters(cost_usd=Decimal("0.50"))
    enf = _make_enforcer(limits=limits, counters=counters)
    assert enf.can_delegate(agent_id="researcher") is True


def test_can_delegate_per_invocation_always_true(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(budget_scope="per_invocation", budget_usd=Decimal("1.00"))
    # Even with cost over budget, per-invocation lets you start a new sub-agent
    # because each delegation gets its own fresh budget.
    counters = RuntimeCounters(cost_usd=Decimal("9.99"))
    enf = _make_enforcer(limits=limits, counters=counters)
    assert enf.can_delegate(agent_id="researcher") is True


# ---------------------------------------------------------------------------
# Health-check uses model_override
# ---------------------------------------------------------------------------


async def test_health_check_uses_health_check_model(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(
        turn_limit=10,
        turn_extension=5,
        health_check_model="openai/gpt-4o-mini",
    )
    counters = RuntimeCounters(turns_used=10, active_turn_limit=10)

    health_check_response = _make_llm_result(
        text=json.dumps(
            {"verdict": "progressing", "reason": "ok", "should_extend": True}
        ),
        cost_usd=Decimal("0.001"),
    )
    main_response = _make_llm_result(cost_usd=Decimal("0.01"))

    llm = _make_mock_llm(completion_results=[health_check_response, main_response])
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    await enf.acompletion(
        [{"role": "user", "content": "thing"}],
        metadata=_make_call_meta(),
    )
    # First call must have been the health-check with model_override set.
    first_call = llm.acompletion.await_args_list[0]
    kwargs = first_call.kwargs
    assert kwargs.get("model_override") == "openai/gpt-4o-mini"
    # ``json_object`` was rejected by LM Studio's qwen with HTTP 400 — we
    # now request ``text`` and parse JSON manually out of the response body.
    assert kwargs.get("response_format") == {"type": "text"}
    # The main call must NOT carry a model_override (we didn't pass one).
    second_call = llm.acompletion.await_args_list[1]
    assert second_call.kwargs.get("model_override") is None


# ---------------------------------------------------------------------------
# Health-check parser: malformed JSON → stuck
# ---------------------------------------------------------------------------


async def test_health_check_garbage_response_treated_as_stuck(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(turn_limit=10, turn_extension=5)
    counters = RuntimeCounters(turns_used=10, active_turn_limit=10)
    bad = _make_llm_result(text="not json", cost_usd=None)
    llm = _make_mock_llm(completion_results=[bad])
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    with pytest.raises(TurnLimitReached):
        await enf.acompletion(
            [{"role": "user", "content": "thing"}],
            metadata=_make_call_meta(),
        )


# ---------------------------------------------------------------------------
# Health-check prompt is compact
# ---------------------------------------------------------------------------


async def test_health_check_prompt_is_short(patch_pricing):
    patch_pricing(_make_pricing())
    limits = RuntimeLimits(turn_limit=2, turn_extension=5)
    counters = RuntimeCounters(turns_used=2, active_turn_limit=2)

    health_check_response = _make_llm_result(
        text=json.dumps(
            {"verdict": "progressing", "reason": "yes", "should_extend": True}
        ),
        cost_usd=None,
    )
    main_response = _make_llm_result(cost_usd=None)
    llm = _make_mock_llm(completion_results=[health_check_response, main_response])
    enf = _make_enforcer(limits=limits, counters=counters, llm=llm)

    # Build a long message history to ensure the enforcer truncates it.
    long_messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Initial goal: build me a thing."}
    ]
    for i in range(50):
        long_messages.append(
            {
                "role": "assistant",
                "content": "x" * 5000,
                "tool_calls": [
                    {
                        "id": f"call_{i}",
                        "function": {"name": "do_thing", "arguments": "{}"},
                    }
                ],
            }
        )
        long_messages.append(
            {"role": "tool", "tool_call_id": f"call_{i}", "content": "ok"}
        )

    await enf.acompletion(long_messages, metadata=_make_call_meta())
    first_call = llm.acompletion.await_args_list[0]
    health_messages = first_call.args[0]
    assert health_messages[0]["role"] == "system"
    # Total payload size for the user content should be much smaller than the
    # raw history (anti-loop probe — not deep analysis).
    user_payload = health_messages[1]["content"]
    assert len(user_payload) < 5000


# ---------------------------------------------------------------------------
# Pricing unknown → estimate falls back to 0 (call still goes through)
# ---------------------------------------------------------------------------


async def test_pricing_unknown_does_not_block_call(patch_pricing):
    patch_pricing(None)
    counters = RuntimeCounters(cost_usd=Decimal("0.10"))
    llm = _make_mock_llm(completion_result=_make_llm_result(cost_usd=None))
    enf = _make_enforcer(counters=counters, llm=llm)

    # Should not raise — pre-flight estimate is 0 when pricing is unknown.
    await enf.acompletion(
        [{"role": "user", "content": "hi"}],
        metadata=_make_call_meta(),
    )
    assert counters.turns_used == 1


# ---------------------------------------------------------------------------
# HealthCheckResult parser smoke (no LLM)
# ---------------------------------------------------------------------------


def test_parse_health_check_response_progressing():
    res = LimitsEnforcer._parse_health_check_response(
        json.dumps({"verdict": "progressing", "reason": "good", "should_extend": True})
    )
    assert res == HealthCheckResult(
        verdict="progressing", reason="good", should_extend=True
    )


def test_parse_health_check_response_stuck_overrides_should_extend():
    res = LimitsEnforcer._parse_health_check_response(
        json.dumps({"verdict": "stuck", "reason": "loop", "should_extend": True})
    )
    # Defensive: stuck verdict forces should_extend False even if model lied.
    assert res.verdict == "stuck"
    assert res.should_extend is False


def test_parse_health_check_response_empty():
    res = LimitsEnforcer._parse_health_check_response("")
    assert res.verdict == "stuck"
    assert res.should_extend is False
