"""PI seat bundles: invite_codes table and sponsored_by_user_id on users

Revision ID: c7d4e2a1f093
Revises: a3c9e1f2b847
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c7d4e2a1f093'
down_revision: Union[str, Sequence[str], None] = 'a3c9e1f2b847'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Add sponsored_by_user_id only if it does not already exist.
    # (create_all does not add columns to existing tables, but this migration
    # may run on a DB where create_all already ran the full schema.)
    row = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='sponsored_by_user_id'"
    )).fetchone()
    if not row:
        op.add_column("users", sa.Column(
            "sponsored_by_user_id", sa.Integer(),
            sa.ForeignKey("users.id"), nullable=True,
        ))

    # Create invite_codes only if it does not already exist.
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id SERIAL PRIMARY KEY,
            code VARCHAR(16) NOT NULL,
            pi_user_id INTEGER NOT NULL REFERENCES users(id),
            stripe_subscription_id VARCHAR,
            redeemed_by_user_id INTEGER REFERENCES users(id),
            redeemed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
    """))
    conn.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_invite_codes_code ON invite_codes(code)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_invite_codes_pi_user_id ON invite_codes(pi_user_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_invite_codes_pi_user_id", "invite_codes")
    op.drop_index("ix_invite_codes_code", "invite_codes")
    op.drop_table("invite_codes")
    op.drop_column("users", "sponsored_by_user_id")
