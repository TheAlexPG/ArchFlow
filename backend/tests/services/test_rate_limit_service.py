"""Tests for app.services.rate_limit_service.

Uses fakeredis.aioredis.FakeRedis so no live Redis is required.
"""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.services.rate_limit_service import (
    RateLimitExceeded,
    RateLimitScope,
    check_and_consume,
    default_limits_for_workspace,
    default_limits_from_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis():
    """Fresh in-memory FakeRedis instance per test."""
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


def _actor_id() -> uuid.UUID:
    return uuid.uuid4()


def _workspace_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Happy-path: 5 invocations under limit succeed
# ---------------------------------------------------------------------------


async def test_happy_path_under_limit(redis):
    actor = _actor_id()
    ws = _workspace_id()
    limits = {
        RateLimitScope.API_KEY_HOUR: 10,
        RateLimitScope.API_KEY_DAY: 100,
        RateLimitScope.WORKSPACE_DAY: 500,
    }
    for _ in range(5):
        await check_and_consume(
            redis=redis,
            actor_kind="api_key",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    # No exception means all 5 succeeded.


# ---------------------------------------------------------------------------
# Limit exceeded: 11th call with limit=10 raises RateLimitExceeded
# ---------------------------------------------------------------------------


async def test_limit_exceeded_on_11th_call(redis):
    actor = _actor_id()
    ws = _workspace_id()
    limits = {
        RateLimitScope.API_KEY_HOUR: 10,
        RateLimitScope.API_KEY_DAY: 100,
        RateLimitScope.WORKSPACE_DAY: 500,
    }
    for _ in range(10):
        await check_and_consume(
            redis=redis,
            actor_kind="api_key",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_consume(
            redis=redis,
            actor_kind="api_key",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    err = exc_info.value
    assert err.limit == 10
    assert RateLimitScope.API_KEY_HOUR in err.scope


# ---------------------------------------------------------------------------
# retry_after_seconds is positive and ≤ TTL of bucket
# ---------------------------------------------------------------------------


async def test_retry_after_is_positive_and_within_ttl(redis):
    actor = _actor_id()
    ws = _workspace_id()
    limits = {
        RateLimitScope.API_KEY_HOUR: 1,
        RateLimitScope.API_KEY_DAY: 100,
        RateLimitScope.WORKSPACE_DAY: 500,
    }
    # First call consumes the only allowed token.
    await check_and_consume(
        redis=redis,
        actor_kind="api_key",
        actor_id=actor,
        workspace_id=ws,
        limits=limits,
    )
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_consume(
            redis=redis,
            actor_kind="api_key",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    err = exc_info.value
    assert err.retry_after_seconds >= 1
    assert err.retry_after_seconds <= 3600  # bucket TTL for API_KEY_HOUR


# ---------------------------------------------------------------------------
# Scoped: api_key actor checks 3 scopes
# ---------------------------------------------------------------------------


async def test_api_key_actor_checks_three_scopes(redis):
    actor = _actor_id()
    ws = _workspace_id()

    # Set workspace limit to 1 so it triggers after the api_key limits pass.
    limits = {
        RateLimitScope.API_KEY_HOUR: 100,
        RateLimitScope.API_KEY_DAY: 100,
        RateLimitScope.WORKSPACE_DAY: 1,
    }
    await check_and_consume(
        redis=redis,
        actor_kind="api_key",
        actor_id=actor,
        workspace_id=ws,
        limits=limits,
    )
    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_consume(
            redis=redis,
            actor_kind="api_key",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    # The workspace:day scope should have tripped.
    assert RateLimitScope.WORKSPACE_DAY in exc_info.value.scope


# ---------------------------------------------------------------------------
# Scoped: user actor checks only 2 scopes (USER_DAY + WORKSPACE_DAY)
# ---------------------------------------------------------------------------


async def test_user_actor_checks_two_scopes(redis):
    actor = _actor_id()
    ws = _workspace_id()

    # Only provide user-relevant limits; api_key scopes are intentionally absent.
    limits = {
        RateLimitScope.USER_DAY: 2,
        RateLimitScope.WORKSPACE_DAY: 1000,
    }

    for _ in range(2):
        await check_and_consume(
            redis=redis,
            actor_kind="user",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )

    with pytest.raises(RateLimitExceeded) as exc_info:
        await check_and_consume(
            redis=redis,
            actor_kind="user",
            actor_id=actor,
            workspace_id=ws,
            limits=limits,
        )
    assert RateLimitScope.USER_DAY in exc_info.value.scope


async def test_user_actor_does_not_check_api_key_scopes(redis):
    """user actor should not be blocked even if api_key buckets would be over limit."""
    actor = _actor_id()
    ws = _workspace_id()

    # api_key scopes are present in limits dict but must not be applied for 'user'.
    limits = {
        RateLimitScope.API_KEY_HOUR: 0,  # would block immediately if checked
        RateLimitScope.API_KEY_DAY: 0,
        RateLimitScope.USER_DAY: 10,
        RateLimitScope.WORKSPACE_DAY: 10,
    }
    # Should succeed: user actor ignores API_KEY_* scopes.
    await check_and_consume(
        redis=redis,
        actor_kind="user",
        actor_id=actor,
        workspace_id=ws,
        limits=limits,
    )


# ---------------------------------------------------------------------------
# default_limits_from_config reads from global Settings (operator-level config)
# ---------------------------------------------------------------------------


def test_default_limits_from_config_uses_settings_values(monkeypatch: pytest.MonkeyPatch):
    """default_limits_from_config() reads each value from app.core.config.settings."""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "agent_rate_limit_api_key_per_hour", 11)
    monkeypatch.setattr(cfg.settings, "agent_rate_limit_api_key_per_day", 22)
    monkeypatch.setattr(cfg.settings, "agent_rate_limit_user_per_day", 33)
    monkeypatch.setattr(cfg.settings, "agent_rate_limit_workspace_per_day", 44)

    limits = default_limits_from_config()
    assert limits[RateLimitScope.API_KEY_HOUR] == 11
    assert limits[RateLimitScope.API_KEY_DAY] == 22
    assert limits[RateLimitScope.USER_DAY] == 33
    assert limits[RateLimitScope.WORKSPACE_DAY] == 44


def test_default_limits_from_config_default_values():
    """Default limits are 10× the original spec defaults (60000/h is the new app-level cap)."""
    limits = default_limits_from_config()
    assert limits[RateLimitScope.API_KEY_HOUR] == 6000
    assert limits[RateLimitScope.API_KEY_DAY] == 60000
    assert limits[RateLimitScope.USER_DAY] == 10000
    assert limits[RateLimitScope.WORKSPACE_DAY] == 100000


def test_default_limits_for_workspace_is_alias(monkeypatch: pytest.MonkeyPatch):
    """The deprecated alias delegates to default_limits_from_config and ignores its arg."""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "agent_rate_limit_api_key_per_hour", 7)

    # Both call paths should return the same result regardless of the arg passed.
    via_alias = default_limits_for_workspace({"api_key_per_hour": 999})
    via_new = default_limits_from_config()
    assert via_alias == via_new
    assert via_alias[RateLimitScope.API_KEY_HOUR] == 7
