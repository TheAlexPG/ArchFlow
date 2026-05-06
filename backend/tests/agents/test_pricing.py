"""Tests for app/agents/pricing.py.

Design notes:
- No real DB required.  Uses a FakeSession (same pattern as
  test_agent_settings_service.py) adapted to handle both
  WorkspaceAgentSetting and ModelPricingCache rows.
- No real network calls.  sync_openrouter_pricing is tested with an
  httpx.MockTransport that returns a canned JSON response.
- All tests use pytest-asyncio (asyncio_mode = "auto").
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.agents import pricing as pricing_module
from app.agents.pricing import (
    ModelPricing,
    _from_litellm_builtin,
    clear_pricing_override,
    get_pricing,
    set_pricing_override,
    sync_openrouter_pricing,
    upsert_cache,
)
from app.models.model_pricing_cache import ModelPricingCache
from app.models.workspace_agent_setting import WorkspaceAgentSetting

# ---------------------------------------------------------------------------
# FakeSession — handles WorkspaceAgentSetting + ModelPricingCache rows
# ---------------------------------------------------------------------------


class FakeSession:
    """Minimal AsyncSession that stores rows in memory.

    Handles execute() for SELECT on both WorkspaceAgentSetting and
    ModelPricingCache.  Keeps them in separate lists to avoid cross-type
    confusion.
    """

    def __init__(self):
        self._setting_rows: list[WorkspaceAgentSetting] = []
        self._cache_rows: list[ModelPricingCache] = []

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def execute(self, stmt):
        # Determine which table we're querying by inspecting the entity
        entity = _get_entity(stmt)
        if entity is ModelPricingCache:
            rows = _filter_cache_rows(stmt, self._cache_rows)
        else:
            rows = _filter_setting_rows(stmt, self._setting_rows)
        return _FakeResult(rows)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(self, obj):
        if isinstance(obj, ModelPricingCache):
            self._cache_rows.append(obj)
        else:
            self._setting_rows.append(obj)

    async def delete(self, obj):
        if isinstance(obj, ModelPricingCache):
            self._cache_rows = [r for r in self._cache_rows if r is not obj]
        else:
            self._setting_rows = [r for r in self._setting_rows if r is not obj]

    async def flush(self):
        pass


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) > 1:
            raise RuntimeError("Multiple rows, expected at most one")
        return self._rows[0]


# ---------------------------------------------------------------------------
# Statement analysis helpers
# ---------------------------------------------------------------------------

_IS_NONE_SENTINEL = object()
_IS_NOT_NONE_SENTINEL = object()


def _get_entity(stmt):
    """Return the mapped class being queried."""
    try:
        # SQLAlchemy select() — froms holds Table objects; use the mapper
        col = list(stmt.columns_clause_froms)[0]
        return col.entity_zero.mapper.class_
    except Exception:
        pass
    # Fallback: inspect columns
    try:
        for col in stmt.inner_columns:
            table = getattr(col, "table", None)
            if table is not None:
                name = getattr(table, "name", "")
                if name == "model_pricing_cache":
                    return ModelPricingCache
                if name == "workspace_agent_setting":
                    return WorkspaceAgentSetting
    except Exception:
        pass
    return WorkspaceAgentSetting  # safe default


def _parse_clause(clause, filters: dict) -> None:
    type_name = type(clause).__name__

    if type_name == "BinaryExpression":
        left = clause.left
        right = clause.right
        op_name = getattr(clause.operator, "__name__", str(clause.operator))
        col_name = getattr(left, "key", None) or getattr(left, "name", None)
        if col_name is None:
            return

        if op_name in ("is_", "is"):
            filters[col_name] = _IS_NONE_SENTINEL
        elif op_name in ("isnot", "is_not"):
            filters[col_name] = _IS_NOT_NONE_SENTINEL
        elif op_name == "in_op":
            val = getattr(right, "value", None)
            if isinstance(val, list):
                filters[col_name] = val
            else:
                filters[col_name] = [val]
        else:
            val = getattr(right, "value", None)
            if val is not None:
                filters[col_name] = val

    elif type_name in ("BooleanClauseList", "ClauseList", "And"):
        for sub in clause.clauses:
            _parse_clause(sub, filters)


def _extract_filters(stmt) -> dict:
    filters: dict = {}
    wc = getattr(stmt, "whereclause", None)
    if wc is None:
        return filters
    _parse_clause(wc, filters)
    return filters


def _matches(row: Any, filters: dict) -> bool:
    for attr, expected in filters.items():
        actual = getattr(row, attr, None)
        if expected is _IS_NONE_SENTINEL:
            if actual is not None:
                return False
        elif expected is _IS_NOT_NONE_SENTINEL:
            if actual is None:
                return False
        elif isinstance(expected, (list, set)):
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _filter_setting_rows(stmt, rows: list[WorkspaceAgentSetting]) -> list:
    if hasattr(stmt, "selects"):
        result = []
        seen_ids: set[int] = set()
        for sub in stmt.selects:
            for row in _filter_setting_rows(sub, rows):
                if id(row) not in seen_ids:
                    result.append(row)
                    seen_ids.add(id(row))
        return result
    filters = _extract_filters(stmt)
    return [r for r in rows if _matches(r, filters)]


def _filter_cache_rows(stmt, rows: list[ModelPricingCache]) -> list:
    filters = _extract_filters(stmt)
    return [r for r in rows if _matches(r, filters)]


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_WS_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_setting(**kwargs) -> WorkspaceAgentSetting:
    defaults = dict(
        workspace_id=_WS_ID,
        agent_id=None,
        key="x",
        value_plain=None,
        value_encrypted=None,
        is_secret=False,
        updated_by=None,
    )
    defaults.update(kwargs)
    return WorkspaceAgentSetting(**defaults)


def _make_cache_row(**kwargs) -> ModelPricingCache:
    from datetime import datetime

    defaults = dict(
        model_id="test/model",
        provider="test",
        input_per_million=Decimal("1.000000"),
        output_per_million=Decimal("2.000000"),
        source="openrouter_api",
        cached_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    return ModelPricingCache(**defaults)


@pytest.fixture(autouse=True)
def clear_memo():
    """Clear the in-process memo cache before each test."""
    pricing_module._MEMO.clear()
    yield
    pricing_module._MEMO.clear()


# ---------------------------------------------------------------------------
# ModelPricing.estimate_cost
# ---------------------------------------------------------------------------


def test_estimate_cost_exact():
    p = ModelPricing(
        model_id="x",
        provider="x",
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("2.00"),
        source="litellm_builtin",
    )
    # 1M input at $1/M + 0.5M output at $2/M = $1 + $1 = $2
    result = p.estimate_cost(1_000_000, 500_000)
    assert result == Decimal("2.000000")


def test_estimate_cost_zeros():
    p = ModelPricing(
        model_id="x",
        provider="x",
        input_per_million=Decimal("0.15"),
        output_per_million=Decimal("0.60"),
        source="litellm_builtin",
    )
    assert p.estimate_cost(0, 0) == Decimal("0.000000")


def test_estimate_cost_full_million_each():
    p = ModelPricing(
        model_id="x",
        provider="x",
        input_per_million=Decimal("1.00"),
        output_per_million=Decimal("1.00"),
        source="litellm_builtin",
    )
    result = p.estimate_cost(1_000_000, 1_000_000)
    assert result == Decimal("2.000000")


# ---------------------------------------------------------------------------
# _from_litellm_builtin
# ---------------------------------------------------------------------------


def test_litellm_builtin_known_model():
    p = _from_litellm_builtin("openai/gpt-4o-mini")
    assert p is not None
    assert p.model_id == "openai/gpt-4o-mini"
    assert p.source == "litellm_builtin"
    # gpt-4o-mini input is $0.15/M, output is $0.60/M (as of spec cutoff)
    assert p.input_per_million > Decimal("0")
    assert p.output_per_million > Decimal("0")
    # Sanity: input cheaper than output (typical for most models)
    assert p.input_per_million < p.output_per_million


def test_litellm_builtin_unknown_model():
    p = _from_litellm_builtin("totally-unknown-model-xyz-999")
    assert p is None


def test_litellm_builtin_provider_derived():
    p = _from_litellm_builtin("openai/gpt-4o-mini")
    assert p is not None
    assert p.provider == "openai"


def test_litellm_builtin_no_prefix_model():
    # 'gpt-4o-mini' (no prefix) should also work
    p = _from_litellm_builtin("gpt-4o-mini")
    assert p is not None
    assert p.source == "litellm_builtin"


def test_litellm_builtin_reasonable_numbers():
    p = _from_litellm_builtin("openai/gpt-4o-mini")
    assert p is not None
    # Per-million prices should be between $0.01 and $100 (sanity check)
    assert Decimal("0.01") <= p.input_per_million <= Decimal("100")
    assert Decimal("0.01") <= p.output_per_million <= Decimal("100")


# ---------------------------------------------------------------------------
# get_pricing — resolution order
# ---------------------------------------------------------------------------


async def test_get_pricing_workspace_override_wins():
    """Layer 1: workspace override exists → returns it."""
    db = FakeSession()

    # Seed override rows
    db._setting_rows.append(
        _make_setting(
            workspace_id=_WS_ID,
            agent_id=None,
            key="model_pricing.openai/gpt-4o-mini.input_per_million",
            value_plain="5.00",
        )
    )
    db._setting_rows.append(
        _make_setting(
            workspace_id=_WS_ID,
            agent_id=None,
            key="model_pricing.openai/gpt-4o-mini.output_per_million",
            value_plain="10.00",
        )
    )

    p = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p is not None
    assert p.source == "workspace_override"
    assert p.input_per_million == Decimal("5.00")
    assert p.output_per_million == Decimal("10.00")


async def test_get_pricing_litellm_fallback():
    """Layer 2: no override, model in litellm.model_cost → returns built-in."""
    db = FakeSession()
    # No workspace rows; gpt-4o-mini IS in litellm.model_cost
    p = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p is not None
    assert p.source == "litellm_builtin"


async def test_get_pricing_cache_fallback():
    """Layer 3: no override, not in litellm, cache hit → returns cache."""
    db = FakeSession()
    db._cache_rows.append(
        _make_cache_row(
            model_id="mycompany/custom-model",
            provider="mycompany",
            input_per_million=Decimal("3.00"),
            output_per_million=Decimal("6.00"),
            source="openrouter_api",
        )
    )

    p = await get_pricing(db, _WS_ID, "mycompany/custom-model")
    assert p is not None
    assert p.source == "openrouter_api"
    assert p.input_per_million == Decimal("3.00")


async def test_get_pricing_none_fallback():
    """Layer 4: no override, no built-in, no cache → returns None."""
    db = FakeSession()
    p = await get_pricing(db, _WS_ID, "unknown-provider/unknown-model-xyz-12345")
    assert p is None


# ---------------------------------------------------------------------------
# Memoization
# ---------------------------------------------------------------------------


async def test_get_pricing_memoized_within_ttl():
    """Second call within TTL does not hit DB again."""
    db = FakeSession()
    call_count = 0

    original_from_workspace = pricing_module._from_workspace_override

    async def counting_override(d, ws, mid):
        nonlocal call_count
        call_count += 1
        return await original_from_workspace(d, ws, mid)

    with patch.object(pricing_module, "_from_workspace_override", counting_override):
        p1 = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
        p2 = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")

    # Only one DB call despite two get_pricing calls
    assert call_count == 1
    # Both calls return the same result
    assert p1 is not None
    assert p2 is not None
    assert p1.source == p2.source


async def test_get_pricing_memo_different_workspaces_independent():
    """Memo is per (workspace_id, model_id)."""
    db = FakeSession()
    ws1 = uuid.uuid4()
    ws2 = uuid.uuid4()

    # Give ws2 an override
    db._setting_rows.append(
        _make_setting(
            workspace_id=ws2,
            agent_id=None,
            key="model_pricing.openai/gpt-4o-mini.input_per_million",
            value_plain="99.00",
        )
    )
    db._setting_rows.append(
        _make_setting(
            workspace_id=ws2,
            agent_id=None,
            key="model_pricing.openai/gpt-4o-mini.output_per_million",
            value_plain="199.00",
        )
    )

    p1 = await get_pricing(db, ws1, "openai/gpt-4o-mini")
    p2 = await get_pricing(db, ws2, "openai/gpt-4o-mini")

    assert p1 is not None
    assert p2 is not None
    # ws1 falls back to litellm; ws2 uses the override
    assert p1.source == "litellm_builtin"
    assert p2.source == "workspace_override"
    assert p2.input_per_million == Decimal("99.00")


# ---------------------------------------------------------------------------
# set_pricing_override / clear_pricing_override
# ---------------------------------------------------------------------------


async def test_set_pricing_override_stores_and_returns():
    """set_pricing_override writes settings rows and returns the override."""
    db = FakeSession()

    p = await set_pricing_override(
        db,
        _WS_ID,
        "custom/my-model",
        input_per_million=Decimal("7.50"),
        output_per_million=Decimal("15.00"),
        updated_by=_USER_ID,
    )

    assert p.source == "workspace_override"
    assert p.input_per_million == Decimal("7.50")
    assert p.output_per_million == Decimal("15.00")
    assert p.provider == "custom"

    # Rows must be in the session
    assert len(db._setting_rows) == 2
    keys = {r.key for r in db._setting_rows}
    assert "model_pricing.custom/my-model.input_per_million" in keys
    assert "model_pricing.custom/my-model.output_per_million" in keys


async def test_set_pricing_override_invalidates_memo():
    """set_pricing_override clears the in-process memo for that model."""
    db = FakeSession()

    # Prime memo with litellm result
    p1 = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p1 is not None
    assert p1.source == "litellm_builtin"

    # Set override → should invalidate memo
    await set_pricing_override(
        db,
        _WS_ID,
        "openai/gpt-4o-mini",
        input_per_million=Decimal("50.00"),
        output_per_million=Decimal("100.00"),
        updated_by=_USER_ID,
    )

    # Next call should pick up the override (not the cached litellm result)
    p2 = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p2 is not None
    assert p2.source == "workspace_override"
    assert p2.input_per_million == Decimal("50.00")


async def test_clear_pricing_override_reverts():
    """clear_pricing_override removes the rows so litellm takes over again."""
    db = FakeSession()

    # Set an override
    await set_pricing_override(
        db,
        _WS_ID,
        "openai/gpt-4o-mini",
        input_per_million=Decimal("50.00"),
        output_per_million=Decimal("100.00"),
        updated_by=_USER_ID,
    )

    p_override = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p_override is not None
    assert p_override.source == "workspace_override"

    # Clear it
    await clear_pricing_override(db, _WS_ID, "openai/gpt-4o-mini", _USER_ID)

    p_reverted = await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")
    assert p_reverted is not None
    assert p_reverted.source == "litellm_builtin"


async def test_clear_pricing_override_invalidates_memo():
    """clear_pricing_override clears memo so next get_pricing re-resolves."""
    db = FakeSession()

    await set_pricing_override(
        db,
        _WS_ID,
        "openai/gpt-4o-mini",
        input_per_million=Decimal("50.00"),
        output_per_million=Decimal("100.00"),
        updated_by=_USER_ID,
    )
    # prime memo with override
    await get_pricing(db, _WS_ID, "openai/gpt-4o-mini")

    # Clear must have blown the memo key
    await clear_pricing_override(db, _WS_ID, "openai/gpt-4o-mini", _USER_ID)
    assert (pricing_module._MEMO.get((_WS_ID, "openai/gpt-4o-mini"))) is None


# ---------------------------------------------------------------------------
# upsert_cache
# ---------------------------------------------------------------------------


async def test_upsert_cache_insert():

    db = FakeSession()
    row = await upsert_cache(
        db,
        model_id="openrouter/x/y",
        provider="openrouter",
        input_per_million=Decimal("0.50"),
        output_per_million=Decimal("1.50"),
        source="openrouter_api",
    )
    assert row.model_id == "openrouter/x/y"
    assert len(db._cache_rows) == 1


async def test_upsert_cache_update():

    db = FakeSession()
    existing = _make_cache_row(
        model_id="openrouter/x/y",
        provider="openrouter",
        input_per_million=Decimal("0.50"),
        output_per_million=Decimal("1.50"),
        source="openrouter_api",
    )
    db._cache_rows.append(existing)

    row = await upsert_cache(
        db,
        model_id="openrouter/x/y",
        provider="openrouter",
        input_per_million=Decimal("0.75"),
        output_per_million=Decimal("2.00"),
        source="openrouter_api",
    )

    # Should have updated the existing row, not added a new one
    assert len(db._cache_rows) == 1
    assert row is existing
    assert row.input_per_million == Decimal("0.75")
    assert row.output_per_million == Decimal("2.00")


# ---------------------------------------------------------------------------
# sync_openrouter_pricing (mocked HTTP)
# ---------------------------------------------------------------------------

_OPENROUTER_MOCK_RESPONSE = {
    "data": [
        {
            "id": "openai/gpt-4o-mini",
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
        },
        {
            "id": "anthropic/claude-3-haiku",
            "pricing": {"prompt": "0.00000025", "completion": "0.00000125"},
        },
        {
            "id": "deepseek/deepseek-r1",
            "pricing": {"prompt": "0.00000055", "completion": "0.00000219"},
        },
        # Should be skipped — missing pricing
        {
            "id": "free-model/no-pricing",
        },
        # Should be skipped — null pricing fields
        {
            "id": "bad/model",
            "pricing": {"prompt": None, "completion": None},
        },
    ]
}


def _make_mock_transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
        )

    return httpx.MockTransport(handler)


async def test_sync_openrouter_pricing_upserts_n_rows():
    db = FakeSession()
    transport = _make_mock_transport(_OPENROUTER_MOCK_RESPONSE)
    async with httpx.AsyncClient(transport=transport) as client:
        count = await sync_openrouter_pricing(db, http=client)

    # 3 valid models (2 skipped)
    assert count == 3
    assert len(db._cache_rows) == 3


async def test_sync_openrouter_pricing_prefixes_model_id():
    db = FakeSession()
    transport = _make_mock_transport(_OPENROUTER_MOCK_RESPONSE)
    async with httpx.AsyncClient(transport=transport) as client:
        await sync_openrouter_pricing(db, http=client)

    model_ids = {r.model_id for r in db._cache_rows}
    # All model IDs should be prefixed with 'openrouter/'
    assert "openrouter/openai/gpt-4o-mini" in model_ids
    assert "openrouter/anthropic/claude-3-haiku" in model_ids
    assert "openrouter/deepseek/deepseek-r1" in model_ids


async def test_sync_openrouter_pricing_correct_values():
    db = FakeSession()
    transport = _make_mock_transport(_OPENROUTER_MOCK_RESPONSE)
    async with httpx.AsyncClient(transport=transport) as client:
        await sync_openrouter_pricing(db, http=client)

    row = next(r for r in db._cache_rows if r.model_id == "openrouter/openai/gpt-4o-mini")
    # 0.00000015 * 1_000_000 = 0.15
    assert row.input_per_million == Decimal("0.15")
    assert row.output_per_million == Decimal("0.6")
    assert row.source == "openrouter_api"


async def test_sync_openrouter_pricing_idempotent():
    """Re-running sync should update existing rows, not duplicate them."""
    db = FakeSession()
    transport = _make_mock_transport(_OPENROUTER_MOCK_RESPONSE)
    async with httpx.AsyncClient(transport=transport) as client:
        count1 = await sync_openrouter_pricing(db, http=client)
        count2 = await sync_openrouter_pricing(db, http=client)

    # Both runs should report 3 rows upserted
    assert count1 == 3
    assert count2 == 3
    # But total cache rows should still be 3 (no duplicates)
    assert len(db._cache_rows) == 3


async def test_sync_openrouter_pricing_empty_response():
    db = FakeSession()
    transport = _make_mock_transport({"data": []})
    async with httpx.AsyncClient(transport=transport) as client:
        count = await sync_openrouter_pricing(db, http=client)
    assert count == 0
    assert len(db._cache_rows) == 0


async def test_sync_openrouter_pricing_all_invalid():
    """All models have missing pricing — 0 rows upserted."""
    db = FakeSession()
    payload = {
        "data": [
            {"id": "x/y"},
            {"id": "a/b", "pricing": {}},
        ]
    }
    transport = _make_mock_transport(payload)
    async with httpx.AsyncClient(transport=transport) as client:
        count = await sync_openrouter_pricing(db, http=client)
    assert count == 0
