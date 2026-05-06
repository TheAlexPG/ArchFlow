"""model_pricing_cache: store cached LLM model pricing for budget tracking

Revision ID: c0dbe5b00010
Revises: c0dbe5b00009
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0dbe5b00010"
down_revision: str | Sequence[str] | None = "c0dbe5b00009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_pricing_cache",
        sa.Column("model_id", sa.String(255), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("input_per_million", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_per_million", sa.Numeric(12, 6), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Index for cleanup queries that filter or delete by provider.
    op.create_index(
        "ix_model_pricing_cache_provider",
        "model_pricing_cache",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_pricing_cache_provider",
        table_name="model_pricing_cache",
    )
    op.drop_table("model_pricing_cache")
