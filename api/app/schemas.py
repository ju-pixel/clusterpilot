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
