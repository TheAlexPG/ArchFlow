"""seed_mcp_a2a_protocols: add MCP and A2A to built-in protocol catalog

Revision ID: c0dbe5b00006
Revises: c0dbe5b00005
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0dbe5b00006"
down_revision: str | Sequence[str] | None = "c0dbe5b00005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_ROWS = [
    {
        "slug": "mcp",
        "name": "MCP",
        "iconify_name": "mdi:message-processing-outline",
        "color": "#D97757",
        "aliases": ["model-context-protocol", "model context protocol"],
    },
    {
        "slug": "a2a",
        "name": "A2A",
        "iconify_name": "mdi:account-switch-outline",
        "color": "#6366F1",
        "aliases": ["agent-to-agent", "agent to agent"],
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        """
        INSERT INTO technologies
            (id, workspace_id, slug, name, iconify_name, category, color, aliases)
        VALUES
            (gen_random_uuid(), NULL, :slug, :name, :iconify_name,
             CAST('PROTOCOL' AS tech_category), :color, :aliases)
        ON CONFLICT (slug) WHERE workspace_id IS NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            iconify_name = EXCLUDED.iconify_name,
            category = EXCLUDED.category,
            color = EXCLUDED.color,
            aliases = EXCLUDED.aliases,
            updated_at = now()
        """
    )
    for row in _NEW_ROWS:
        bind.execute(insert_sql, row)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM technologies "
            "WHERE workspace_id IS NULL AND slug = ANY(:slugs)"
        ),
        {"slugs": [r["slug"] for r in _NEW_ROWS]},
    )
