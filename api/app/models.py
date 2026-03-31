from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


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
