from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ---------- User ----------

class UserOut(BaseModel):
    id: int
    clerk_id: str
    email: str
    subscription_status: str
    managed_api_key_prefix: Optional[str]
    notify_on_start: bool
    notify_on_complete: bool
    notify_on_fail: bool
    notify_on_walltime_warn: bool
    ntfy_topic: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Jobs ----------

class JobUpsert(BaseModel):
    """Sent by the local daemon on each job state change."""
    slurm_job_id: str
    job_name: Optional[str] = None
    cluster_name: str
    partition: Optional[str] = None
    status: str
    script: Optional[str] = None
    log_tail: Optional[str] = None
    walltime_requested: Optional[str] = None
    walltime_consumed: Optional[str] = None
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobOut(BaseModel):
    id: int
    slurm_job_id: str
    job_name: Optional[str]
    cluster_name: str
    partition: Optional[str]
    status: str
    script: Optional[str]
    log_tail: Optional[str]
    walltime_requested: Optional[str]
    walltime_consumed: Optional[str]
    fieldnotes_run_id: Optional[str]
    submitted_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- API keys ----------

class KeyOut(BaseModel):
    """Returned once on creation/rotation; never stored in plaintext."""
    key: str
    prefix: str


# ---------- Notification preferences ----------

class NotifyPrefsIn(BaseModel):
    notify_on_start: bool
    notify_on_complete: bool
    notify_on_fail: bool
    notify_on_walltime_warn: bool
    ntfy_topic: Optional[str] = None


class NotifyPrefsOut(BaseModel):
    notify_on_start: bool
    notify_on_complete: bool
    notify_on_fail: bool
    notify_on_walltime_warn: bool
    ntfy_topic: Optional[str]

    model_config = {"from_attributes": True}


# ---------- Health ----------

class HealthOut(BaseModel):
    status: str
    db: str
