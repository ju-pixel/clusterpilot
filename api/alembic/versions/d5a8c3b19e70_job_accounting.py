"""Job accounting: what sacct reported the scheduler reserved

Adds the fields the local TUI already knew and the dashboard could not show
(account, array_spec, status_detail, efficiency, exit_code) plus the numeric
accounting a usage report has to add up (alloc_cpus, alloc_gpus, alloc_nodes,
runtime_seconds, core_seconds, gpu_seconds).

Every column is nullable and nothing is backfilled: rows written before this
release keep NULLs, which a report must read as "not reported" rather than
zero.

Revision ID: d5a8c3b19e70
Revises: b2f5d0c71a94
Create Date: 2026-08-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd5a8c3b19e70'
down_revision: Union[str, Sequence[str], None] = 'b2f5d0c71a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, type). All nullable, no server default: absent means unknown.
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("account", sa.String()),
    ("array_spec", sa.String()),
    ("status_detail", sa.String()),
    ("efficiency", sa.String()),
    ("exit_code", sa.String()),
    ("alloc_cpus", sa.Integer()),
    ("alloc_gpus", sa.Integer()),
    ("alloc_nodes", sa.Integer()),
    ("runtime_seconds", sa.Integer()),
    ("core_seconds", sa.Float()),
    ("gpu_seconds", sa.Float()),
)


def upgrade() -> None:
    conn = op.get_bind()
    for name, type_ in _COLUMNS:
        # create_all may already have written the full schema on a fresh
        # database, so add each column only when it is genuinely missing.
        row = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='jobs' AND column_name=:name"
        ), {"name": name}).fetchone()
        if not row:
            op.add_column("jobs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("jobs", name)
