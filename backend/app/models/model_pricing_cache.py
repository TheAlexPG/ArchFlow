from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModelPricingCache(Base):
    """Cached LLM model pricing used for budget tracking and cost estimation.

    Populated from three possible sources, listed by priority:
    1. ``workspace_override`` — manually entered by workspace admin.
    2. ``litellm_builtin``   — from LiteLLM's built-in ``model_cost`` mapping.
    3. ``openrouter_api``    — fetched from OpenRouter's model list API
                              (hourly background sync when openrouter is used).

    No foreign keys — ``model_id`` is an external identifier (e.g.
    ``"openai/gpt-4o-mini"``) not tied to any internal table.
    """

    __tablename__ = "model_pricing_cache"

    model_id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    input_per_million: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False
    )
    output_per_million: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False
    )
    # 'litellm_builtin' | 'openrouter_api' | 'workspace_override'
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        nullable=False,
        default=datetime.utcnow,
    )

    __table_args__ = (
        # Supports cleanup queries and filtering by provider.
        Index("ix_model_pricing_cache_provider", "provider"),
    )
