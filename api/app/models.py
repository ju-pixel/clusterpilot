from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Subscription statuses that count as "paying" for gating purposes. Stripe
# writes its own literal into User.subscription_status, so a user inside the
# 14-day trial is stored as "trialing", not "active". Anything that gates on a
# live subscription must use this set rather than comparing against "active".
SUBSCRIBED_STATUSES: frozenset[str] = frozenset({"active", "trialing"})


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    pi_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    redeemed_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pi_user: Mapped["User"] = relationship("User", foreign_keys=[pi_user_id], back_populates="issued_invite_codes")
    redeemed_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[redeemed_by_user_id])

    @property
    def redeemed(self) -> bool:
        return self.redeemed_by_user_id is not None


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clerk_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    subscription_status: Mapped[str] = mapped_column(String, default="free", nullable=False)
    # Managed API key: only the bcrypt hash and a 4-char prefix for display
    managed_api_key_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    managed_api_key_prefix: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    # PI group: set when this user's access is sponsored by a PI's seat bundle
    sponsored_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # Notification preferences
    notify_on_start: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_fail: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_walltime_warn: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ntfy_topic: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    jobs: Mapped[List[Job]] = relationship("Job", back_populates="user", lazy="select")
    issued_invite_codes: Mapped[List["InviteCode"]] = relationship(
        "InviteCode", foreign_keys="InviteCode.pi_user_id", back_populates="pi_user", lazy="select"
    )


class GenerationUsage(Base):
    """Hosted AI generations counted per user per calendar month (UTC).

    One row per user per month, created on the first successful generation of
    that month and incremented thereafter. ``total`` counts every successful
    generation, ``opus`` only those actually served by an Opus model, so a
    request that fell back to Sonnet raises ``total`` alone. A month with no
    generations has no row at all; absence reads as zero.
    """

    __tablename__ = "generation_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "month", name="uq_generation_usage_user_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    opus: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Idempotent upsert key: one user cannot have two jobs with the same
        # SLURM ID on the same cluster.
        UniqueConstraint("user_id", "slurm_job_id", "cluster_name", name="uq_job_per_user_cluster"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slurm_job_id: Mapped[str] = mapped_column(String, nullable=False)
    job_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cluster_name: Mapped[str] = mapped_column(String, nullable=False)
    partition: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # PENDING/RUNNING/COMPLETED/FAILED/CANCELLED
    script: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # SLURM script text
    log_tail: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Last N lines of SLURM log
    walltime_requested: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # HH:MM:SS string
    walltime_consumed: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # What the local TUI already knew and the dashboard could not show.
    account: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    array_spec: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "0-9", "1-100%5"
    status_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "5R/27PD"
    efficiency: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # seff summary
    exit_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "<exit>:<signal>"
    # Accounting from sacct. NULL means the cluster did not report it, which
    # is not zero: a usage report must skip these rows rather than add them up.
    alloc_cpus: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alloc_gpus: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alloc_nodes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    runtime_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    core_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gpu_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Placeholder for Track F: populated when the user links a Fieldnotes run.
    fieldnotes_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="jobs")
