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
    # IF NOT EXISTS throughout, for the same reason as c7d4e2a1f093: the app
    # calls Base.metadata.create_all at startup, so on any database the app
    # has already booted against, this table exists before the migration runs.
    # That is exactly the state of production, which is stamped at
    # c7d4e2a1f093 and has been serving the allowance routes off a table
    # create_all made. A plain create_table fails there with DuplicateTable
    # and takes every later migration down with it.
    conn = op.get_bind()
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS generation_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            month VARCHAR(7) NOT NULL,
            total INTEGER NOT NULL DEFAULT 0,
            opus INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            -- One row per user per calendar month. The upsert in
            -- app/services/allowance.py relies on this to catch the race
            -- where two concurrent generations both try to create the
            -- month's first row.
            CONSTRAINT uq_generation_usage_user_month UNIQUE (user_id, month)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_generation_usage_user_id "
        "ON generation_usage(user_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_generation_usage_user_id", "generation_usage")
    op.drop_table("generation_usage")
