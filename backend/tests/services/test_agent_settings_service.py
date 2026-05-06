"""Tests for app/services/agent_settings_service.py.

Design notes:
- These tests do NOT require a live Postgres instance.  The SQLAlchemy
  ``AsyncSession`` is replaced by a ``FakeSession`` that stores rows in memory
  and implements just enough of the Session interface to exercise the service
  logic.
- ``AGENTS_SECRET_KEY`` is injected per-test via ``monkeypatch`` (same
  pattern as test_secret_service.py).
- All tests are sync-compatible because the async helpers are thin wrappers
  around in-memory data; pytest-asyncio handles the event loop transparently.
"""

from __future__ import annotations

import importlib
import uuid
from decimal import Decimal
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture()
def with_key(valid_key: str, monkeypatch: pytest.MonkeyPatch):
    """Inject AGENTS_SECRET_KEY into settings and reload the service modules."""
    monkeypatch.setenv("AGENTS_SECRET_KEY", valid_key)
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", SecretStr(valid_key))

    import app.services.agent_settings_service as svc  # noqa: PLC0415
    import app.services.secret_service as ss

    importlib.reload(ss)
    importlib.reload(svc)
    return svc


@pytest.fixture()
def without_key(monkeypatch: pytest.MonkeyPatch):
    """Ensure AGENTS_SECRET_KEY is absent."""
    monkeypatch.delenv("AGENTS_SECRET_KEY", raising=False)
    from app.core import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "agents_secret_key", None)

    import app.services.agent_settings_service as svc  # noqa: PLC0415
    import app.services.secret_service as ss

    importlib.reload(ss)
    importlib.reload(svc)
    return svc


# ---------------------------------------------------------------------------
# In-memory AsyncSession fake
# ---------------------------------------------------------------------------


class FakeSession:
    """Minimal AsyncSession stand-in backed by an in-memory list of rows.

    Implements:
    - ``execute(stmt)`` → returns a result whose ``scalars().all()`` returns
      matching rows.
    - ``add(obj)`` / ``delete(obj)`` / ``flush()`` (no-op flush).
    """

    def __init__(self):
        self._rows: list[Any] = []

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def execute(self, stmt):
        """Naively evaluate the SQLAlchemy statement by inspecting its WHERE
        clauses at a high level.  We delegate to ``_evaluate_stmt`` which
        returns a list of matching rows.
        """
        rows = _evaluate_stmt(stmt, self._rows)
        return _FakeResult(rows)

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add(self, obj):
        self._rows.append(obj)

    async def delete(self, obj):
        self._rows = [r for r in self._rows if r is not obj]

    async def flush(self):
        pass  # no-op for in-memory store


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
# Statement evaluator (interprets the WHERE predicates we actually use)
# ---------------------------------------------------------------------------

from app.models.workspace_agent_setting import WorkspaceAgentSetting  # noqa: E402

_IS_NONE_SENTINEL = object()
_IS_NOT_NONE_SENTINEL = object()


def _matches_row(row: WorkspaceAgentSetting, filters: dict) -> bool:
    """Return True if *row* satisfies all key=value pairs in *filters*."""
    for attr, expected in filters.items():
        actual = getattr(row, attr)
        if expected is _IS_NONE_SENTINEL:
            if actual is not None:
                return False
        elif expected is _IS_NOT_NONE_SENTINEL:
            if actual is None:
                return False
        elif isinstance(expected, (set, list)):
            # IN clause
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _parse_clause(clause, filters: dict) -> None:
    """Recursively parse a single WHERE clause element into *filters*.

    Handles the exact clause shapes produced by the service:
    - BinaryExpression: col == val, col IS NULL, col IN (...)
    - BooleanClauseList (AND): multiple conditions
    """
    type_name = type(clause).__name__

    if type_name == "BinaryExpression":
        left = clause.left
        right = clause.right
        op_name = getattr(clause.operator, "__name__", str(clause.operator))
        col_name = getattr(left, "key", None) or getattr(left, "name", None)
        if col_name is None:
            return

        if op_name in ("is_", "is"):
            # col IS NULL
            filters[col_name] = _IS_NONE_SENTINEL
        elif op_name in ("isnot", "is_not"):
            filters[col_name] = _IS_NOT_NONE_SENTINEL
        elif op_name == "in_op":
            # IN clause: right is BindParameter with expanding=True, value=list
            val = getattr(right, "value", None)
            if isinstance(val, list):
                filters[col_name] = val
            else:
                filters[col_name] = [val]
        else:
            # Plain equality: right is BindParameter, value is the literal
            val = getattr(right, "value", None)
            if val is not None:
                filters[col_name] = val

    elif type_name in ("BooleanClauseList", "ClauseList", "And"):
        for sub in clause.clauses:
            _parse_clause(sub, filters)

    # Other clause types (e.g. ordering) — ignore silently.


def _extract_filters(stmt) -> dict:
    """Walk the WHERE clause tree and build a key→value filter dict."""
    filters: dict = {}
    wc = getattr(stmt, "whereclause", None)
    if wc is None:
        return filters
    _parse_clause(wc, filters)
    return filters


def _evaluate_stmt(stmt, all_rows: list) -> list:
    """Return subset of *all_rows* that match *stmt*'s WHERE predicates.

    For UNION ALL statements (used in resolve_for_agent) we evaluate each
    branch and combine while preserving order and deduplicating by identity.
    """
    # CompoundSelect (UNION / UNION ALL / INTERSECT / EXCEPT)
    if hasattr(stmt, "selects"):
        result = []
        seen_ids: set[int] = set()
        for sub in stmt.selects:
            for row in _evaluate_stmt(sub, all_rows):
                if id(row) not in seen_ids:
                    result.append(row)
                    seen_ids.add(id(row))
        return result

    filters = _extract_filters(stmt)
    return [r for r in all_rows if _matches_row(r, filters)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WS_ID = uuid.uuid4()
_USER_ID = uuid.uuid4()


def _make_row(**kwargs) -> WorkspaceAgentSetting:
    defaults = dict(
        workspace_id=_WS_ID,
        agent_id=None,
        key="litellm_provider",
        value_plain=None,
        value_encrypted=None,
        is_secret=False,
        updated_by=None,
    )
    defaults.update(kwargs)
    return WorkspaceAgentSetting(**defaults)


# ---------------------------------------------------------------------------
# set_setting + get_setting round-trip (plaintext)
# ---------------------------------------------------------------------------


async def test_set_and_get_plaintext(with_key):
    svc = with_key
    db = FakeSession()

    row = await svc.set_setting(
        db, _WS_ID, None, "litellm_provider", value_plain={"value": "anthropic"}
    )
    assert row.key == "litellm_provider"
    assert row.value_plain == {"value": "anthropic"}
    assert row.is_secret is False
    assert row.value_encrypted is None

    fetched = await svc.get_setting(db, _WS_ID, None, "litellm_provider")
    assert fetched is row
    assert fetched.value_plain == {"value": "anthropic"}


async def test_set_plaintext_upserts_existing(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(db, _WS_ID, None, "litellm_provider", value_plain="openai")
    await svc.set_setting(db, _WS_ID, None, "litellm_provider", value_plain="anthropic")

    # Only one row should exist.
    fetched = await svc.get_setting(db, _WS_ID, None, "litellm_provider")
    assert fetched is not None
    assert fetched.value_plain == "anthropic"
    assert len(db._rows) == 1


# ---------------------------------------------------------------------------
# set_setting + get_setting round-trip (secret)
# ---------------------------------------------------------------------------


async def test_set_and_get_secret_round_trip(with_key):
    svc = with_key
    db = FakeSession()

    row = await svc.set_setting(
        db, _WS_ID, None, "litellm_api_key", value_secret="sk-supersecret"
    )
    assert row.is_secret is True
    assert row.value_encrypted is not None
    assert isinstance(row.value_encrypted, bytes)
    # The raw plaintext must NOT be stored in value_plain.
    assert row.value_plain is None

    fetched = await svc.get_setting(db, _WS_ID, None, "litellm_api_key")
    assert fetched is row
    # Decrypt using secret_service directly to confirm round-trip.
    from app.services import secret_service as ss  # noqa: PLC0415

    decrypted = ss.decrypt(fetched.value_encrypted)
    assert decrypted == "sk-supersecret"


async def test_secret_not_in_value_plain(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(
        db, _WS_ID, None, "litellm_api_key", value_secret="top-secret-key"
    )
    fetched = await svc.get_setting(db, _WS_ID, None, "litellm_api_key")
    assert fetched.value_plain is None


# ---------------------------------------------------------------------------
# Delete path (value_plain=None AND value_secret=None)
# ---------------------------------------------------------------------------


async def test_delete_removes_row(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(db, _WS_ID, None, "analytics_consent", value_plain="full")
    assert len(db._rows) == 1

    await svc.set_setting(db, _WS_ID, None, "analytics_consent")  # both None → delete
    assert len(db._rows) == 0

    fetched = await svc.get_setting(db, _WS_ID, None, "analytics_consent")
    assert fetched is None


async def test_delete_nonexistent_is_noop(with_key):
    svc = with_key
    db = FakeSession()

    # Should not raise even when the row does not exist.
    await svc.set_setting(db, _WS_ID, None, "does_not_exist")
    assert len(db._rows) == 0


# ---------------------------------------------------------------------------
# Mutual exclusion guard
# ---------------------------------------------------------------------------


async def test_both_values_raises(with_key):
    svc = with_key
    db = FakeSession()

    with pytest.raises(ValueError, match="exactly one"):
        await svc.set_setting(
            db, _WS_ID, None, "litellm_api_key",
            value_plain="plain",
            value_secret="secret",
        )


# ---------------------------------------------------------------------------
# Secret without key raises RuntimeError
# ---------------------------------------------------------------------------


async def test_secret_without_key_raises(without_key):
    svc = without_key
    db = FakeSession()

    with pytest.raises(RuntimeError, match="AGENTS_SECRET_KEY"):
        await svc.set_setting(
            db, _WS_ID, None, "litellm_api_key", value_secret="sk-oops"
        )


# ---------------------------------------------------------------------------
# list_settings
# ---------------------------------------------------------------------------


async def test_list_settings_all(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(db, _WS_ID, None, "litellm_provider", value_plain="openai")
    await svc.set_setting(db, _WS_ID, "general", "turn_limit", value_plain=100)
    await svc.set_setting(db, _WS_ID, "researcher", "turn_limit", value_plain=30)

    all_rows = await svc.list_settings(db, _WS_ID)
    assert len(all_rows) == 3


async def test_list_settings_filtered_by_agent(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(db, _WS_ID, None, "litellm_provider", value_plain="openai")
    await svc.set_setting(db, _WS_ID, "general", "turn_limit", value_plain=100)
    await svc.set_setting(db, _WS_ID, "researcher", "turn_limit", value_plain=30)

    general_rows = await svc.list_settings(db, _WS_ID, agent_id="general")
    assert len(general_rows) == 1
    assert general_rows[0].key == "turn_limit"
    assert general_rows[0].agent_id == "general"


# ---------------------------------------------------------------------------
# resolve_for_agent — merging order
# ---------------------------------------------------------------------------


async def test_resolve_uses_field_default_when_no_rows(with_key):
    svc = with_key
    db = FakeSession()

    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    # Field defaults from the dataclass.
    assert resolved.litellm_provider == "openai"
    assert resolved.turn_limit == 200
    assert resolved.budget_usd == Decimal("1.00")
    assert resolved.analytics_consent == "full"


async def test_resolve_applies_agent_defaults(with_key):
    svc = with_key
    db = FakeSession()

    # AGENT_DEFAULTS for "researcher" sets turn_limit=50.
    resolved = await svc.resolve_for_agent(db, _WS_ID, "researcher")
    assert resolved.turn_limit == 50
    assert resolved.budget_usd == Decimal("0.20")


async def test_resolve_global_row_overrides_agent_default(with_key):
    svc = with_key
    db = FakeSession()

    # Global workspace row for turn_limit.
    db._rows.append(
        _make_row(workspace_id=_WS_ID, agent_id=None, key="turn_limit", value_plain=75)
    )

    resolved = await svc.resolve_for_agent(db, _WS_ID, "researcher")
    # Global row (75) beats AGENT_DEFAULTS["researcher"]["turn_limit"] (50).
    assert resolved.turn_limit == 75


async def test_resolve_agent_row_overrides_global(with_key):
    svc = with_key
    db = FakeSession()

    # Global workspace sets provider to "anthropic".
    db._rows.append(
        _make_row(
            workspace_id=_WS_ID, agent_id=None, key="litellm_provider", value_plain="anthropic"
        )
    )
    # Per-agent row overrides with "openai".
    db._rows.append(
        _make_row(
            workspace_id=_WS_ID,
            agent_id="general",
            key="litellm_provider",
            value_plain="openai",
        )
    )

    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    assert resolved.litellm_provider == "openai"


async def test_resolve_full_priority_chain(with_key):
    """Verify all four levels: per-agent > global > AGENT_DEFAULTS > field default."""
    svc = with_key
    db = FakeSession()

    # 1. Field default: turn_limit = 200
    # 2. AGENT_DEFAULTS["researcher"]["turn_limit"] = 50
    # 3. Global workspace row: turn_limit = 75
    # 4. Per-agent row: turn_limit = 10  ← must win
    db._rows.append(
        _make_row(workspace_id=_WS_ID, agent_id=None, key="turn_limit", value_plain=75)
    )
    db._rows.append(
        _make_row(
            workspace_id=_WS_ID, agent_id="researcher", key="turn_limit", value_plain=10
        )
    )

    resolved = await svc.resolve_for_agent(db, _WS_ID, "researcher")
    assert resolved.turn_limit == 10


# ---------------------------------------------------------------------------
# ResolvedAgentSettings.litellm_api_key() — decrypt on access
# ---------------------------------------------------------------------------


async def test_litellm_api_key_returns_none_when_not_configured(with_key):
    svc = with_key
    db = FakeSession()

    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    assert resolved.litellm_api_key() is None


async def test_litellm_api_key_decrypts_when_configured(with_key):
    svc = with_key
    db = FakeSession()

    # Store an encrypted secret row.
    secret_row = await svc.set_setting(
        db, _WS_ID, None, "litellm_api_key", value_secret="sk-my-production-key"
    )
    assert secret_row.is_secret is True

    # Place it manually into the fake session rows (set_setting already did so
    # via add(), so it's there; resolve_for_agent will query and pick it up).
    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    assert resolved.litellm_api_key() == "sk-my-production-key"


async def test_litellm_api_key_not_exposed_as_plain_attribute(with_key):
    svc = with_key
    db = FakeSession()

    await svc.set_setting(
        db, _WS_ID, None, "litellm_api_key", value_secret="sk-hidden"
    )

    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    # _litellm_api_key_encrypted is private by convention; raw bytes should
    # never be a public string.
    raw = resolved._litellm_api_key_encrypted  # noqa: SLF001
    assert isinstance(raw, bytes)
    assert b"sk-hidden" not in raw  # encrypted, not plaintext


# ---------------------------------------------------------------------------
# Budget Decimal coercion
# ---------------------------------------------------------------------------


async def test_budget_usd_coerced_to_decimal(with_key):
    svc = with_key
    db = FakeSession()

    # JSONB may store numeric as float; service must coerce to Decimal.
    db._rows.append(
        _make_row(workspace_id=_WS_ID, agent_id=None, key="budget_usd", value_plain=2.5)
    )

    resolved = await svc.resolve_for_agent(db, _WS_ID, "general")
    assert isinstance(resolved.budget_usd, Decimal)
    assert resolved.budget_usd == Decimal("2.5")
