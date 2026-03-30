"""initial

Revision ID: 8f761b9f51e1
Revises:
Create Date: 2026-03-30 00:47:33.120990

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8f761b9f51e1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clerk_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("subscription_status", sa.String(), nullable=False, server_default="free"),
        sa.Column("managed_api_key_hash", sa.String(), nullable=True),
        sa.Column("managed_api_key_prefix", sa.String(8), nullable=True),
        sa.Column("notify_on_start", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_on_complete", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_on_fail", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_on_walltime_warn", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("ntfy_topic", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_clerk_id", "users", ["clerk_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slurm_job_id", sa.String(), nullable=False),
        sa.Column("cluster_name", sa.String(), nullable=False),
        sa.Column("partition", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("script", sa.String(), nullable=True),
        sa.Column("log_tail", sa.String(), nullable=True),
        sa.Column("walltime_requested", sa.String(), nullable=True),
        sa.Column("walltime_consumed", sa.String(), nullable=True),
        sa.Column("fieldnotes_run_id", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slurm_job_id", "cluster_name", name="uq_job_per_user_cluster"),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])

    # Trigger to auto-update updated_at on row change (Postgres only)
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in ("users", "jobs"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    for table in ("jobs", "users"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at;")
    op.drop_table("jobs")
    op.drop_table("users")
