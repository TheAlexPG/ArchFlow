"""merge undo and repo link heads

Revision ID: f359350166f3
Revises: 0246c9846364, c0dbe5b00014
Create Date: 2026-05-05 21:59:52.566145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f359350166f3'
down_revision: Union[str, Sequence[str], None] = ('0246c9846364', 'c0dbe5b00014')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
