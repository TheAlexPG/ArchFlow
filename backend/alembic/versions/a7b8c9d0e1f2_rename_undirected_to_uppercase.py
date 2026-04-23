"""Rename connection_direction enum value 'undirected' to 'UNDIRECTED'.

The initial schema declared the enum with UPPERCASE values (UNIDIRECTIONAL,
BIDIRECTIONAL) because SQLAlchemy's Enum column serialises Python enum
members by `.name` (uppercase) rather than `.value`. The original migration
that added the 'undirected' value used lowercase, which creates a runtime
mismatch — the app sends 'UNDIRECTED' but Postgres only knows 'undirected'.

This migration renames the existing lowercase enum value to UPPERCASE so
the column value matches the python enum name. Idempotent via a guard:
the DO block is a no-op if 'undirected' has already been renamed.

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-04-23 17:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'connection_direction' AND e.enumlabel = 'undirected'
          ) THEN
            ALTER TYPE connection_direction RENAME VALUE 'undirected' TO 'UNDIRECTED';
          END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = 'connection_direction' AND e.enumlabel = 'UNDIRECTED'
          ) THEN
            ALTER TYPE connection_direction RENAME VALUE 'UNDIRECTED' TO 'undirected';
          END IF;
        END$$;
        """
    )
