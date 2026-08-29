"""generation_usage: monthly hosted generation counts per user

Revision ID: b2f5d0c71a94
Revises: c7d4e2a1f093
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2f5d0c71a94'
down_revision: Union[str, Sequence[str], None] = 'c7d4e2a1f093'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # One row per user per calendar month. The upsert in
        # app/services/allowance.py relies on this to catch the race where two
        # concurrent generations both try to create the month's first row.
        sa.UniqueConstraint("user_id", "month", name="uq_generation_usage_user_month"),
    )
    op.create_index("ix_generation_usage_user_id", "generation_usage", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_generation_usage_user_id", "generation_usage")
    op.drop_table("generation_usage")
