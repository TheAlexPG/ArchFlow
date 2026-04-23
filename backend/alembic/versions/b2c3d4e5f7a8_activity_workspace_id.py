"""Add workspace_id to activity_log and backfill from target tables.

Revision ID: b2c3d4e5f7a8
Revises: eb9e2003d7b9
Create Date: 2026-04-23 12:00:00.000000

Strategy
--------
ActivityLog has three target_type values:
  - 'object'     → model_objects.workspace_id
  - 'connection' → connections have no workspace_id; derive via source_id →
                   model_objects.workspace_id
  - 'diagram'    → diagrams.workspace_id

The column is added nullable so the deploy is safe for rows created before
this migration runs.  Forward writes will always populate it (see
activity_service.py).  Old NULL rows remain in the DB but are excluded from
workspace-scoped feeds, which is the correct privacy posture.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f7a8"
down_revision: str | Sequence[str] | None = "eb9e2003d7b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the nullable column.
    op.add_column(
        "activity_log",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # 2. Create an index for fast workspace-scoped queries.
    op.create_index(
        "ix_activity_log_workspace_id",
        "activity_log",
        ["workspace_id"],
    )

    # 3. Backfill: target_type = 'object'
    op.execute(
        """
        UPDATE activity_log al
        SET    workspace_id = mo.workspace_id
        FROM   model_objects mo
        WHERE  al.target_type = 'OBJECT'
          AND  al.target_id   = mo.id
          AND  al.workspace_id IS NULL
        """
    )

    # 4. Backfill: target_type = 'diagram'
    op.execute(
        """
        UPDATE activity_log al
        SET    workspace_id = d.workspace_id
        FROM   diagrams d
        WHERE  al.target_type = 'DIAGRAM'
          AND  al.target_id   = d.id
          AND  al.workspace_id IS NULL
        """
    )

    # 5. Backfill: target_type = 'connection'
    #    Connections have no direct workspace_id; derive via source_id.
    op.execute(
        """
        UPDATE activity_log al
        SET    workspace_id = mo.workspace_id
        FROM   connections c
        JOIN   model_objects mo ON mo.id = c.source_id
        WHERE  al.target_type = 'CONNECTION'
          AND  al.target_id   = c.id
          AND  al.workspace_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_activity_log_workspace_id", table_name="activity_log")
    op.drop_column("activity_log", "workspace_id")
