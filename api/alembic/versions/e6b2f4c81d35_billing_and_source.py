"""Billing weight and the provenance of each accounting figure

sacct cannot reach slurmdbd from Alliance login nodes (clusterpilot#47), so
ClusterPilot measures reserved time itself from squeue and its own poll
cycles. `accounting_source` says which of the two produced a row's figures so
a usage report never presents a measurement as a scheduler accounting record.

`billing` is SLURM's own weighting of an allocation and is what a scheduler
charges against a grant. It is not proportional to CPU count: a Narval job
with four CPUs and four A100s bills at 16000, a plain eight-CPU job at 8.

Revision ID: e6b2f4c81d35
Revises: d5a8c3b19e70
Create Date: 2026-08-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e6b2f4c81d35'
down_revision: Union[str, Sequence[str], None] = 'd5a8c3b19e70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("alloc_billing", sa.Integer()),
    ("billing_seconds", sa.Float()),
    ("accounting_source", sa.String()),
)


def upgrade() -> None:
    conn = op.get_bind()
    for name, type_ in _COLUMNS:
        row = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='jobs' AND column_name=:name"
        ), {"name": name}).fetchone()
        if not row:
            op.add_column("jobs", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("jobs", name)
