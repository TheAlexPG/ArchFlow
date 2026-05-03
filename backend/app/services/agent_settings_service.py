"""Workspace agent settings service.

Provides CRUD for ``workspace_agent_setting`` rows plus resolution logic that
merges per-agent rows → global workspace rows → AGENT_DEFAULTS → dataclass
field defaults into a single ``ResolvedAgentSettings`` object consumed by the
agent runtime.

Secret handling:
- Only ``litellm_api_key`` is a secret in Phase 1.
- Encryption is performed via ``secret_service.encrypt`` (Fernet).
- ``ResolvedAgentSettings.litellm_api_key()`` decrypts on demand.
- The encrypted bytes are never exposed as a public attribute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_agent_setting import WorkspaceAgentSetting
from app.services import secret_service

# ---------------------------------------------------------------------------
# Per-agent defaults for known builtin agents (see spec §3 max_steps + models)
# ---------------------------------------------------------------------------

AGENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {"turn_limit": 200, "budget_usd": Decimal("1.00")},
    "researcher": {"turn_limit": 50, "budget_usd": Decimal("0.20")},
    "diagram-explainer": {
        "turn_limit": 20,
        "budget_usd": Decimal("0.05"),
        "model": "openai/gpt-4o-mini",
    },
}


# ---------------------------------------------------------------------------
# Resolved settings dataclass
# ---------------------------------------------------------------------------


@dataclass
class ResolvedAgentSettings:
    """Merged settings for one agent in one workspace.

    Resolution order: per-agent specific → workspace global → hardcoded default.
    Secret values are decrypted only on access via the explicit getter.
    """

    workspace_id: UUID
    agent_id: str

    # LLM
    litellm_provider: str = "openai"
    litellm_base_url: str | None = None
    litellm_model: str = "openai/gpt-4o-mini"  # per-agent override applied
    # Manual context-window override (tokens). Used when LiteLLM cannot
    # auto-detect the model's window (e.g. local LM Studio / Ollama models).
    litellm_context_window: int | None = None
    _litellm_api_key_encrypted: bytes | None = None  # never expose raw

    # Context / compaction
    context_threshold: float = 0.5
    context_strategy: str = "hermes_summarize"
    context_ladder: list[str] = field(
        default_factory=lambda: [
            "trim_large_tool_results",
            "drop_oldest_tool_messages",
            "summarize_oldest_half",
            "hard_truncate_keep_recent",
        ]
    )
    tool_result_trim_threshold_tokens: int = 2000

    # Limits
    turn_limit: int = 200
    turn_extension: int = 50
    budget_usd: Decimal = Decimal("1.00")
    budget_scope: str = "per_invocation"  # 'per_invocation' | 'per_request'
    on_budget_exhausted: str = "summarize_and_finalize"
    health_check_model: str = "openai/gpt-4o-mini"

    # Privacy / external
    analytics_consent: str = "full"  # 'off' | 'errors_only' | 'full'
    agent_edits_policy: str = "ask"  # 'live_only' | 'drafts_only' | 'ask'

    def litellm_api_key(self) -> str | None:
        """Decrypt and return the LLM API key, or None if not configured."""
        if self._litellm_api_key_encrypted is None:
            return None
        return secret_service.decrypt(self._litellm_api_key_encrypted)


# ---------------------------------------------------------------------------
# Key → field mapping used by resolve_for_agent
# ---------------------------------------------------------------------------

# Maps a setting ``key`` (as stored in the DB) to the corresponding field name
# on ``ResolvedAgentSettings``.  Only plain (non-secret) fields are listed
# here.  The ``litellm_api_key`` secret is handled separately.
_KEY_TO_FIELD: dict[str, str] = {
    # LLM
    "litellm_provider": "litellm_provider",
    "litellm_base_url": "litellm_base_url",
    "litellm_model_default": "litellm_model",
    "litellm_context_window": "litellm_context_window",
    # per-agent override (applied under agent_id prefix, see resolver)
    "model": "litellm_model",
    # Context
    "context_threshold": "context_threshold",
    "context_strategy": "context_strategy",
    "context_ladder": "context_ladder",
    "tool_result_trim_threshold_tokens": "tool_result_trim_threshold_tokens",
    # Limits
    "turn_limit": "turn_limit",
    "turn_extension": "turn_extension",
    "budget_usd": "budget_usd",
    "budget_scope": "budget_scope",
    "on_budget_exhausted": "on_budget_exhausted",
    "health_check_model": "health_check_model",
    # Privacy
    "analytics_consent": "analytics_consent",
    "agent_edits_policy": "agent_edits_policy",
}

# Fields that need Decimal coercion when read back from JSONB (which stores
# numbers as float/str depending on the original write path).
_DECIMAL_FIELDS = {"budget_usd"}


def _coerce_value(field_name: str, raw: Any) -> Any:
    """Coerce a raw JSONB value to the expected Python type for *field_name*."""
    if field_name in _DECIMAL_FIELDS and raw is not None:
        return Decimal(str(raw))
    return raw


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


async def get_setting(
    db: AsyncSession,
    workspace_id: UUID,
    agent_id: str | None,
    key: str,
) -> WorkspaceAgentSetting | None:
    """Fetch single (workspace_id, agent_id, key) row, no resolution merging."""
    stmt = select(WorkspaceAgentSetting).where(
        WorkspaceAgentSetting.workspace_id == workspace_id,
        WorkspaceAgentSetting.key == key,
        (
            WorkspaceAgentSetting.agent_id == agent_id
            if agent_id is not None
            else WorkspaceAgentSetting.agent_id.is_(None)
        ),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def set_setting(
    db: AsyncSession,
    workspace_id: UUID,
    agent_id: str | None,
    key: str,
    *,
    value_plain: Any | None = None,
    value_secret: str | None = None,
    updated_by: UUID | None = None,
) -> WorkspaceAgentSetting:
    """Upsert (workspace_id, agent_id, key).

    - Encrypts ``value_secret`` with ``secret_service`` before writing.
    - Mutually exclusive: pass exactly one of ``value_plain`` or
      ``value_secret``.
    - To clear a setting, pass both as ``None`` — this deletes the row and
      raises ``LookupError`` (the row is gone; callers should not use the
      return value after a delete).  The "delete" path is separate from the
      "upsert" path to keep the function signature consistent with the spec.

    Raises:
        ValueError – if both ``value_plain`` and ``value_secret`` are provided.
        RuntimeError – if ``value_secret`` is provided but
            ``AGENTS_SECRET_KEY`` is not configured.
    """
    if value_plain is not None and value_secret is not None:
        raise ValueError(
            "Provide exactly one of value_plain or value_secret, not both."
        )

    # Clear path — delete the row.
    if value_plain is None and value_secret is None:
        existing = await get_setting(db, workspace_id, agent_id, key)
        if existing is not None:
            await db.delete(existing)
            await db.flush()
        # Return a sentinel object that callers can inspect if needed, but the
        # spec says "deletes row" so we satisfy the return type with the
        # (now-deleted) object.  Callers should not persist or re-use it.
        if existing is not None:
            return existing
        # Nothing to delete — return a transient object (not in DB).
        return WorkspaceAgentSetting(
            workspace_id=workspace_id,
            agent_id=agent_id,
            key=key,
            is_secret=False,
        )

    # Encrypt secret value.
    encrypted: bytes | None = None
    if value_secret is not None:
        if not secret_service.is_available():
            raise RuntimeError(
                "Cannot store a secret setting: AGENTS_SECRET_KEY is not configured. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        encrypted = secret_service.encrypt(value_secret)

    existing = await get_setting(db, workspace_id, agent_id, key)
    if existing is not None:
        # Update in-place.
        if value_secret is not None:
            existing.value_plain = None
            existing.value_encrypted = encrypted
            existing.is_secret = True
        else:
            existing.value_plain = value_plain
            existing.value_encrypted = None
            existing.is_secret = False
        if updated_by is not None:
            existing.updated_by = updated_by
        await db.flush()
        return existing

    # Insert new row.
    row = WorkspaceAgentSetting(
        workspace_id=workspace_id,
        agent_id=agent_id,
        key=key,
        value_plain=value_plain if value_secret is None else None,
        value_encrypted=encrypted,
        is_secret=value_secret is not None,
        updated_by=updated_by,
    )
    db.add(row)
    await db.flush()
    return row


async def list_settings(
    db: AsyncSession,
    workspace_id: UUID,
    agent_id: str | None = None,
) -> list[WorkspaceAgentSetting]:
    """List rows for workspace (and optionally one agent_id).

    Ordered by (agent_id NULLS FIRST, key).
    """
    stmt = select(WorkspaceAgentSetting).where(
        WorkspaceAgentSetting.workspace_id == workspace_id,
    )
    if agent_id is not None:
        stmt = stmt.where(WorkspaceAgentSetting.agent_id == agent_id)

    stmt = stmt.order_by(
        WorkspaceAgentSetting.agent_id.asc().nulls_first(),
        WorkspaceAgentSetting.key.asc(),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


async def resolve_for_agent(
    db: AsyncSession,
    workspace_id: UUID,
    agent_id: str,
) -> ResolvedAgentSettings:
    """Build ResolvedAgentSettings from DB rows + AGENT_DEFAULTS + spec defaults.

    Resolution order (highest → lowest priority):
      1. per-(workspace, agent_id, key) row wins
      2. per-(workspace, NULL agent_id, key) row wins
      3. AGENT_DEFAULTS[agent_id][key] wins
      4. dataclass field default
    """
    # Fetch all rows for this workspace where agent_id matches OR is NULL.
    # NOTE: SQLAlchemy ORM + UNION ALL + asyncpg scalars() returns the first
    # column (PK UUID) instead of mapped instances.  Use a plain SELECT with
    # an OR clause and partition in Python instead.
    stmt = select(WorkspaceAgentSetting).where(
        WorkspaceAgentSetting.workspace_id == workspace_id,
        (
            (WorkspaceAgentSetting.agent_id == agent_id)
            | WorkspaceAgentSetting.agent_id.is_(None)
        ),
    )
    result = await db.execute(stmt)
    rows: list[WorkspaceAgentSetting] = list(result.scalars().all())

    # Split into buckets — agent-specific rows win over global ones.
    agent_rows: dict[str, WorkspaceAgentSetting] = {}
    global_rows: dict[str, WorkspaceAgentSetting] = {}
    for row in rows:
        if row.agent_id == agent_id:
            agent_rows[row.key] = row
        else:
            global_rows[row.key] = row

    resolved = ResolvedAgentSettings(workspace_id=workspace_id, agent_id=agent_id)

    # Apply AGENT_DEFAULTS first (lowest priority from DB perspective).
    agent_defaults = AGENT_DEFAULTS.get(agent_id, {})
    for default_key, default_val in agent_defaults.items():
        field_name = _KEY_TO_FIELD.get(default_key)
        if field_name is not None:
            setattr(resolved, field_name, _coerce_value(field_name, default_val))

    def _apply_row(row: WorkspaceAgentSetting) -> None:
        """Write a single DB row's value into *resolved*."""
        if row.key == "litellm_api_key" and row.is_secret:
            # Secret — store encrypted bytes; decrypted on access.
            resolved._litellm_api_key_encrypted = row.value_encrypted  # noqa: SLF001
            return
        field_name = _KEY_TO_FIELD.get(row.key)
        if field_name is None:
            return  # Unknown key — skip gracefully.
        raw = row.value_plain
        # JSONB object stored as dict (e.g. {"value": ...}) — unwrap if
        # service used a wrapper, or use dict directly for list/complex.
        val = raw.get("value", raw) if isinstance(raw, dict) else raw
        setattr(resolved, field_name, _coerce_value(field_name, val))

    # Apply global rows (lower priority than agent-specific).
    for row in global_rows.values():
        _apply_row(row)

    # Apply per-agent rows (highest priority — overwrite globals).
    for row in agent_rows.values():
        _apply_row(row)

    return resolved
