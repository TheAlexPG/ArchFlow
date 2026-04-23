"""technology_catalog: create technologies table and seed built-in entries

Revision ID: c0dbe5b00001
Revises: eb9e2003d7b9
"""
import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00001"
down_revision: str | Sequence[str] | None = "eb9e2003d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CATEGORY_VALUES = (
    "language",
    "framework",
    "database",
    "cloud",
    "saas",
    "tool",
    "protocol",
    "other",
)


def _seed_rows() -> list[dict]:
    # Seed file lives at backend/data/technologies.json, three levels up from
    # this migration file (backend/alembic/versions/<this>.py).
    data_path = Path(__file__).resolve().parents[2] / "data" / "technologies.json"
    with data_path.open() as f:
        return json.load(f)


def upgrade() -> None:
    tech_category = postgresql.ENUM(*_CATEGORY_VALUES, name="tech_category")
    tech_category.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "technologies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("iconify_name", sa.String(120), nullable=False),
        sa.Column(
            "category",
            postgresql.ENUM(*_CATEGORY_VALUES, name="tech_category", create_type=False),
            nullable=False,
        ),
        sa.Column("color", sa.String(9), nullable=True),
        sa.Column("aliases", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )

    op.create_index(
        "uq_technologies_builtin_slug",
        "technologies",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    op.create_index(
        "uq_technologies_workspace_slug",
        "technologies",
        ["workspace_id", "slug"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NOT NULL"),
    )
    op.create_index("ix_technologies_workspace_id", "technologies", ["workspace_id"])
    op.create_index("ix_technologies_category", "technologies", ["category"])

    # Seed built-in rows. Idempotent via ON CONFLICT on the built-in partial
    # unique index (slug WHERE workspace_id IS NULL).
    bind = op.get_bind()
    rows = _seed_rows()
    if not rows:
        return

    insert_sql = sa.text(
        """
        INSERT INTO technologies
            (id, workspace_id, slug, name, iconify_name, category, color, aliases)
        VALUES
            (gen_random_uuid(), NULL, :slug, :name, :iconify_name,
             CAST(:category AS tech_category), :color, :aliases)
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

    for row in rows:
        bind.execute(
            insert_sql,
            {
                "slug": row["slug"],
                "name": row["name"],
                "iconify_name": row["iconify_name"],
                "category": row["category"],
                "color": row.get("color"),
                "aliases": row.get("aliases") or None,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_technologies_category", table_name="technologies")
    op.drop_index("ix_technologies_workspace_id", table_name="technologies")
    op.drop_index("uq_technologies_workspace_slug", table_name="technologies")
    op.drop_index("uq_technologies_builtin_slug", table_name="technologies")
    op.drop_table("technologies")
    postgresql.ENUM(name="tech_category").drop(op.get_bind(), checkfirst=True)
