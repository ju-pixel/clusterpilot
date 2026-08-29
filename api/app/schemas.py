from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


# ---------- User ----------

class UserOut(BaseModel):
    id: int
    clerk_id: str
    email: str
    subscription_status: str
    managed_api_key_prefix: Optional[str]
    sponsored_by_user_id: Optional[int]
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
    # Sent since 0.7.0. Older clients omit them and the row keeps its NULLs,
    # so the API and the client can be deployed in either order.
    account: Optional[str] = None
    array_spec: Optional[str] = None
    status_detail: Optional[str] = None
    efficiency: Optional[str] = None
    exit_code: Optional[str] = None
    alloc_cpus: Optional[int] = None
    alloc_gpus: Optional[int] = None
    alloc_nodes: Optional[int] = None
    runtime_seconds: Optional[int] = None
    core_seconds: Optional[float] = None
    gpu_seconds: Optional[float] = None
    alloc_billing: Optional[int] = None
    billing_seconds: Optional[float] = None
    accounting_source: Optional[str] = None


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
    account: Optional[str]
    array_spec: Optional[str]
    status_detail: Optional[str]
    efficiency: Optional[str]
    exit_code: Optional[str]
    alloc_cpus: Optional[int]
    alloc_gpus: Optional[int]
    alloc_nodes: Optional[int]
    runtime_seconds: Optional[int]
    core_seconds: Optional[float]
    gpu_seconds: Optional[float]
    alloc_billing: Optional[int]
    billing_seconds: Optional[float]
    accounting_source: Optional[str]

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


# ---------- Billing ----------

class CheckoutRequest(BaseModel):
    """Body of ``POST /users/me/checkout``.

    ``interval`` picks the Stripe price: the founding monthly price or the
    yearly one (two months free). The route takes the body as optional, so a
    dashboard built before the annual option existed still gets monthly.
    """
    interval: Literal["month", "year"] = "month"


class SubscriptionOut(BaseModel):
    """The plan a subscriber is on, read live from Stripe for the Account page."""
    interval: str    # "month" or "year"
    amount: int      # per seat per interval, in minor units, before any discount
    currency: str    # ISO code in lower case, as Stripe reports it
    quantity: int    # seats: 1 for a researcher, 3 or more for a PI bundle
    status: str      # Stripe's subscription status ("trialing", "active", ...)


# ---------- PI seat bundles ----------

class PICheckoutRequest(BaseModel):
    quantity: int  # validated >= 3 in the route
    interval: Literal["month", "year"] = "month"  # same prices as a researcher seat, less 15%


class InviteCodeOut(BaseModel):
    code: str
    redeemed: bool
    redeemed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class RedeemRequest(BaseModel):
    code: str


# ---------- Health ----------

class HealthOut(BaseModel):
    status: str
    db: str
