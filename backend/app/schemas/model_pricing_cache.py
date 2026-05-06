from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    """Internal representation of resolved model pricing.

    Used by ``pricing.py`` during layered resolution (workspace override →
    LiteLLM builtin → OpenRouter API).  Not directly serialised to the DB.
    """

    model_id: str = Field(..., description='E.g. "openai/gpt-4o-mini".')
    provider: str = Field(
        ...,
        description='Provider slug, e.g. "openai", "anthropic", "openrouter".',
    )
    input_per_million: Decimal = Field(
        ..., description="Cost in USD per 1 million input tokens."
    )
    output_per_million: Decimal = Field(
        ..., description="Cost in USD per 1 million output tokens."
    )
    source: str = Field(
        ...,
        description=(
            "Resolution source: "
            "'litellm_builtin' | 'openrouter_api' | 'workspace_override'."
        ),
    )


class ModelPricingRead(ModelPricing):
    """API-side representation that includes cache timestamp for UI display."""

    cached_at: datetime

    model_config = {"from_attributes": True}


class ModelPricingOverride(BaseModel):
    """Request body for a manual workspace-level pricing override.

    ``provider`` is auto-derived from the ``model_id`` path component on the
    server; callers only supply the two price fields.
    """

    input_per_million: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Cost in USD per 1 million input tokens.",
    )
    output_per_million: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Cost in USD per 1 million output tokens.",
    )
