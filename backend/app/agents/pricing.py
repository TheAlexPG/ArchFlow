"""
Pricing resolver — layered $/token lookup for budget tracking.

Resolution order:
  1. workspace override (agent_settings with agent_id=NULL)
  2. litellm.model_cost built-in
  3. model_pricing_cache table (populated by sync_openrouter_pricing)
  4. None — caller treats as "pricing unknown, budget tracking disabled"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_pricing_cache import ModelPricingCache
from app.services import agent_settings_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ModelPricing dataclass
# ---------------------------------------------------------------------------


@dataclass
class ModelPricing:
    model_id: str
    provider: str
    input_per_million: Decimal
    output_per_million: Decimal
    source: str  # 'workspace_override' | 'litellm_builtin' | 'openrouter_api'

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> Decimal:
        cost_in = (Decimal(tokens_in) / Decimal("1_000_000")) * self.input_per_million
        cost_out = (Decimal(tokens_out) / Decimal("1_000_000")) * self.output_per_million
        return (cost_in + cost_out).quantize(Decimal("0.000001"))


# ---------------------------------------------------------------------------
# In-process memo cache
# ---------------------------------------------------------------------------

# key: (workspace_id, model_id) → (ModelPricing | None, expiry datetime)
_MEMO: dict[tuple[UUID, str], tuple[ModelPricing | None, datetime]] = {}
_MEMO_TTL_SECONDS = 300  # 5 minutes


def _memo_get(workspace_id: UUID, model_id: str) -> tuple[bool, ModelPricing | None]:
    """Return (hit, value). hit=True means cache had a valid (non-expired) entry."""
    key = (workspace_id, model_id)
    entry = _MEMO.get(key)
    if entry is None:
        return False, None
    pricing, expiry = entry
    if datetime.now(tz=UTC) >= expiry:
        del _MEMO[key]
        return False, None
    return True, pricing


def _memo_set(workspace_id: UUID, model_id: str, pricing: ModelPricing | None) -> None:
    expiry = datetime.now(tz=UTC) + timedelta(seconds=_MEMO_TTL_SECONDS)
    _MEMO[(workspace_id, model_id)] = (pricing, expiry)


def _memo_invalidate(workspace_id: UUID, model_id: str) -> None:
    _MEMO.pop((workspace_id, model_id), None)


# ---------------------------------------------------------------------------
# Provider derivation helper
# ---------------------------------------------------------------------------


def _derive_provider(model_id: str) -> str:
    """Derive provider slug from model_id prefix (before first '/'), or 'custom'."""
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    return "custom"


# ---------------------------------------------------------------------------
# Layer 1: workspace override read helper
# ---------------------------------------------------------------------------


async def _from_workspace_override(
    db: AsyncSession,
    workspace_id: UUID,
    model_id: str,
) -> ModelPricing | None:
    """Read workspace override from agent_settings (agent_id=NULL).

    Keys: 'model_pricing.{model_id}.input_per_million'
          'model_pricing.{model_id}.output_per_million'
    """
    input_key = f"model_pricing.{model_id}.input_per_million"
    output_key = f"model_pricing.{model_id}.output_per_million"

    input_row = await agent_settings_service.get_setting(db, workspace_id, None, input_key)
    output_row = await agent_settings_service.get_setting(db, workspace_id, None, output_key)

    if input_row is None or output_row is None:
        return None

    try:
        raw_in = input_row.value_plain
        raw_out = output_row.value_plain
        # value_plain may be stored as a string Decimal or numeric
        input_val = Decimal(str(raw_in))
        output_val = Decimal(str(raw_out))
    except Exception:
        logger.warning(
            "Failed to parse workspace pricing override for model %s in workspace %s",
            model_id,
            workspace_id,
        )
        return None

    return ModelPricing(
        model_id=model_id,
        provider=_derive_provider(model_id),
        input_per_million=input_val,
        output_per_million=output_val,
        source="workspace_override",
    )


# ---------------------------------------------------------------------------
# Layer 2: litellm built-in
# ---------------------------------------------------------------------------


def _from_litellm_builtin(model_id: str) -> ModelPricing | None:
    """Read litellm.model_cost dict, return ModelPricing or None.

    LiteLLM stores costs per single token (input_cost_per_token); we convert
    to per-million. Lookup strategy:
      1. Try model_id as-is (exact).
      2. Strip the first path component (e.g. 'openai/gpt-4o-mini' → 'gpt-4o-mini').
    """
    entry = litellm.model_cost.get(model_id)
    if entry is None and "/" in model_id:
        short = model_id.split("/", 1)[1]
        entry = litellm.model_cost.get(short)

    if entry is None:
        return None

    input_per_token = entry.get("input_cost_per_token")
    output_per_token = entry.get("output_cost_per_token")

    if input_per_token is None or output_per_token is None:
        return None

    input_per_million = Decimal(str(input_per_token)) * Decimal("1_000_000")
    output_per_million = Decimal(str(output_per_token)) * Decimal("1_000_000")

    return ModelPricing(
        model_id=model_id,
        provider=_derive_provider(model_id),
        input_per_million=input_per_million,
        output_per_million=output_per_million,
        source="litellm_builtin",
    )


# ---------------------------------------------------------------------------
# Layer 3: model_pricing_cache table
# ---------------------------------------------------------------------------


async def _from_cache(db: AsyncSession, model_id: str) -> ModelPricing | None:
    """Query model_pricing_cache table for the row, return ModelPricing or None."""
    stmt = select(ModelPricingCache).where(ModelPricingCache.model_id == model_id)
    result = await db.execute(stmt)
    row: ModelPricingCache | None = result.scalar_one_or_none()
    if row is None:
        return None
    return ModelPricing(
        model_id=row.model_id,
        provider=row.provider,
        input_per_million=row.input_per_million,
        output_per_million=row.output_per_million,
        source=row.source,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_pricing(
    db: AsyncSession,
    workspace_id: UUID,
    model_id: str,
) -> ModelPricing | None:
    """Return ModelPricing for (workspace, model) using layered resolution.

    Order:
      1. workspace override (model_pricing.{model}.input_per_million /
         output_per_million in workspace_agent_setting, agent_id=NULL)
      2. litellm.model_cost[model_id] — built-in pricing
      3. model_pricing_cache table (refreshed by background openrouter sync)
      4. None — caller treats as "pricing unknown, budget tracking disabled"

    Memoized in-process for 5 minutes per (workspace_id, model_id) to avoid DB
    on every LLM call. Cache invalidated when set_pricing_override is called for
    this workspace+model.
    """
    hit, cached = _memo_get(workspace_id, model_id)
    if hit:
        return cached

    # Layer 1: workspace override
    pricing = await _from_workspace_override(db, workspace_id, model_id)
    if pricing is not None:
        _memo_set(workspace_id, model_id, pricing)
        return pricing

    # Layer 2: litellm built-in (synchronous dict lookup, no DB)
    pricing = _from_litellm_builtin(model_id)
    if pricing is not None:
        _memo_set(workspace_id, model_id, pricing)
        return pricing

    # Layer 3: model_pricing_cache table
    pricing = await _from_cache(db, model_id)
    if pricing is not None:
        _memo_set(workspace_id, model_id, pricing)
        return pricing

    # Layer 4: unknown
    logger.warning(
        "Pricing unknown for model %s in workspace %s — budget tracking disabled",
        model_id,
        workspace_id,
    )
    _memo_set(workspace_id, model_id, None)
    return None


async def set_pricing_override(
    db: AsyncSession,
    workspace_id: UUID,
    model_id: str,
    *,
    input_per_million: Decimal,
    output_per_million: Decimal,
    updated_by: UUID,
) -> ModelPricing:
    """Save manual workspace override via agent_settings_service.set_setting.

    Stores under keys 'model_pricing.{model_id}.input_per_million' and
    'model_pricing.{model_id}.output_per_million'.
    Provider derived from model_id prefix (before '/'), or 'custom' if no prefix.
    Invalidates _MEMO[(workspace_id, model_id)].
    """
    input_key = f"model_pricing.{model_id}.input_per_million"
    output_key = f"model_pricing.{model_id}.output_per_million"

    await agent_settings_service.set_setting(
        db,
        workspace_id,
        None,
        input_key,
        value_plain=str(input_per_million),
        updated_by=updated_by,
    )
    await agent_settings_service.set_setting(
        db,
        workspace_id,
        None,
        output_key,
        value_plain=str(output_per_million),
        updated_by=updated_by,
    )

    _memo_invalidate(workspace_id, model_id)

    return ModelPricing(
        model_id=model_id,
        provider=_derive_provider(model_id),
        input_per_million=input_per_million,
        output_per_million=output_per_million,
        source="workspace_override",
    )


async def clear_pricing_override(
    db: AsyncSession,
    workspace_id: UUID,
    model_id: str,
    updated_by: UUID,
) -> None:
    """Delete the workspace override (revert to litellm/cache resolution).
    Invalidates _MEMO.
    """
    input_key = f"model_pricing.{model_id}.input_per_million"
    output_key = f"model_pricing.{model_id}.output_per_million"

    await agent_settings_service.set_setting(
        db,
        workspace_id,
        None,
        input_key,
        updated_by=updated_by,
    )
    await agent_settings_service.set_setting(
        db,
        workspace_id,
        None,
        output_key,
        updated_by=updated_by,
    )

    _memo_invalidate(workspace_id, model_id)


async def upsert_cache(
    db: AsyncSession,
    *,
    model_id: str,
    provider: str,
    input_per_million: Decimal,
    output_per_million: Decimal,
    source: str,
) -> ModelPricingCache:
    """Insert-or-update model_pricing_cache row. Used by background OpenRouter sync."""
    stmt = select(ModelPricingCache).where(ModelPricingCache.model_id == model_id)
    result = await db.execute(stmt)
    row: ModelPricingCache | None = result.scalar_one_or_none()

    if row is not None:
        row.provider = provider
        row.input_per_million = input_per_million
        row.output_per_million = output_per_million
        row.source = source
        row.cached_at = datetime.utcnow()
    else:
        row = ModelPricingCache(
            model_id=model_id,
            provider=provider,
            input_per_million=input_per_million,
            output_per_million=output_per_million,
            source=source,
            cached_at=datetime.utcnow(),
        )
        db.add(row)

    await db.flush()
    return row


# ---------------------------------------------------------------------------
# OpenRouter sync
# ---------------------------------------------------------------------------

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


async def sync_openrouter_pricing(
    db: AsyncSession,
    *,
    http: httpx.AsyncClient | None = None,
) -> int:
    """Fetch /models from OpenRouter and upsert into model_pricing_cache.

    Returns count of upserted rows. Skips models whose pricing fields are missing.

    Pricing fields in OpenRouter response:
      pricing.prompt      (per token, string number) — convert to per-million Decimal
      pricing.completion

    Model IDs are prefixed with 'openrouter/' for our cache (so they don't collide
    with litellm built-in keys for the same upstream model).

    Caller is responsible for invoking this on a schedule — we don't run our own
    background task here. Could be wired via FastAPI startup + asyncio.create_task,
    but task 013 / runtime can decide.
    """
    own_client = http is None
    if own_client:
        http = httpx.AsyncClient(timeout=30.0)

    try:
        response = await http.get(OPENROUTER_MODELS_URL)
        response.raise_for_status()
        payload = response.json()
    finally:
        if own_client:
            await http.aclose()

    models = payload.get("data", [])
    count = 0

    for model in models:
        model_id_raw: str | None = model.get("id")
        pricing: dict | None = model.get("pricing")

        if not model_id_raw or not pricing:
            continue

        prompt_str = pricing.get("prompt")
        completion_str = pricing.get("completion")

        if prompt_str is None or completion_str is None:
            continue

        try:
            # OpenRouter returns per-token price as a string float
            input_per_token = Decimal(str(prompt_str))
            output_per_token = Decimal(str(completion_str))
        except Exception:
            logger.debug("Skipping model %s: invalid pricing values", model_id_raw)
            continue

        # Skip models where pricing is 0 or negative (free models / bad data)
        # We still cache them, but we do require they parse correctly.

        input_per_million = input_per_token * Decimal("1_000_000")
        output_per_million = output_per_token * Decimal("1_000_000")

        # Prefix with 'openrouter/' to avoid collisions with litellm built-in
        cache_model_id = (
            f"openrouter/{model_id_raw}"
            if not model_id_raw.startswith("openrouter/")
            else model_id_raw
        )

        provider = _derive_provider(cache_model_id)

        await upsert_cache(
            db,
            model_id=cache_model_id,
            provider=provider,
            input_per_million=input_per_million,
            output_per_million=output_per_million,
            source="openrouter_api",
        )
        count += 1

    return count
