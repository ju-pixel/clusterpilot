"""add job_name to jobs

Revision ID: a3c9e1f2b847
Revises: 8f761b9f51e1
Create Date: 2026-03-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a3c9e1f2b847'
down_revision: Union[str, Sequence[str], None] = '8f761b9f51e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("job_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "job_name")
